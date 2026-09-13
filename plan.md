# Personal Media Companion — Implementation Plan

| | |
|---|---|
| **Version** | 2.0 — rewritten to align with spec.md v2.0, which redefines Media Companion as a multi-user product. Multi-user architecture (accounts, authentication, per-account ownership of library/taste-profile/recommendation data) is now planned as core, foundational work rather than a late addition, and the recommendation-engine phase reflects the Gemini-primary architecture (semantic candidate selection + deterministic objective validation, with a deterministic pipeline as its fallback) rather than an extraction-only design. |
| **Date** | 2026-09-10 |
| **Basis** | `spec.md` v2.0 |
| **Priority** | Get a working, deployed vertical slice early, then layer the rest on a live app |
| **Status** | This document describes the intended implementation plan and its dependency order — it is not a progress report. See version control / project tracking for current build status. |

This document is the implementation plan for the product specified in
`spec.md` v2.0. It answers *what needs to be built, in what order, and how
each phase is verified against the spec* — not *what has already been
built*. Where this plan and the spec ever appear to disagree, the spec is
authoritative.

---

## 1. Guiding Principles

1. **Deploy before building features.** Stand up an empty-but-live frontend +
   backend + Postgres before writing features, so deployment risk is retired
   first.
2. **Vertical slices.** Each phase ends with something demonstrable and
   tested end-to-end, not a half-built layer.
3. **Authentication is foundational, not a patch.** Every account-owned
   entity (library entry, series progress, taste profile, recommendation
   session) is designed with a required owner from the start (spec §6, §11,
   §13). There is no "single-user first, multi-user later" step in this
   plan — accounts exist before any owned feature is built, so every later
   phase's UI and API are demonstrable against a fully enforced backend.
4. **The LLM call stays bounded** (spec §8.2, §9.0, §10): one request, low
   token cap, JSON-only structured output, one short timeout, at most one
   retry, no tools/multi-turn/agent loop. Per spec v2.0 this bounded call is
   the **primary** source of both the structured preference object and the
   semantic candidate title list (spec §9.0) — not extraction-only. The only
   other LLM use anywhere is the optional `mood_tags` enrichment on add
   (spec §6.4), a separate, equally bounded call.
5. **Secrets server-side only** (spec FR9): the frontend talks only to the
   backend; all API keys and the JWT signing key are backend env vars.
6. **Follow the spec's open-decision defaults** (spec §15) unless a blocker
   forces otherwise: Open Library primary, split deploy, N = 8, weights
   0.50/0.35/0.15, slider rating input, `mood_tags` computed on add.
7. **No paid or personal-subscription runtime dependency.** The deployed app
   must run with no Anthropic access; the LLM provider is optional and
   swappable, and every LLM-touched feature has a deterministic path
   (spec §10, §18).
8. **Ownership is enforced at a single choke point per entity**, not
   scattered per-endpoint checks — a nonexistent resource and a resource
   owned by a different account must be indistinguishable to the API
   (spec §6.1, §11).

---

## 2. Architecture & Component Responsibilities

### 2.1 Frontend — Next.js / React (Vercel)

| Responsibility | Notes |
|---|---|
| Auth UI | login/register pages; token storage; `Authorization: Bearer` header attached to every API request from one central client function |
| Route guarding | protected pages redirect to login when no valid session is present; auth-aware navigation (login/logout state) |
| Search UI | free-text query, type filter, results grid |
| Library UI | list + filter by status/type, item cards — always the authenticated account's own library |
| Item detail & edit | status, rating (slider, 0.5 steps), review, favourite; series season/episode progress |
| Recommendation UI | request box; render the single optional clarifying question; ranked results with reason + availability |
| Responsive layout | desktop + mobile widths (spec NFR1) |

Holds **no** API keys and no JWT signing secret. Env vars: backend base URL
only.

### 2.2 Backend — FastAPI / Python (Render or equivalent)

| Module | Responsibility |
|---|---|
| **Auth service** | password hashing (bcrypt), JWT issuance/verification, register/authenticate; a `get_current_user` dependency used by every protected route |
| **API layer** | REST endpoints for auth, search, library CRUD, series progress, taste profile, recommendation session. Search and media-details stay public/unauthenticated (stateless, provider-facing); every other endpoint requires `get_current_user` |
| **External clients** | TMDb client (search/discover, details, watch providers, region IN); Book client (Open Library primary, Google Books fallback). Also used to resolve Gemini-suggested titles by name (spec §9.0.1) |
| **Normalization** | map provider payloads → common `media_item` shape (spec §6.1, §6.4 buckets), including per-season episode counts (`season_episode_counts`) |
| **Library service** | upsert the shared `media_item`; create/update a user's `library_entry` + `series_progress`; validate progress bounds and derive `seasons_completed` server-side (spec §5.1). Every operation requires and is scoped by `user_id`, routed through a single ownership choke point (`get_entry`) |
| **Taste-profile service** | recompute a derived profile per account on every rating/status change (spec §6.3, FR10) — one row per account, `user_id` is the primary key; reads only that account's own `library_entry` rows |
| **Recommendation orchestrator** | the session state machine (spec §8.1); sparsity rule (§8.3); tries the Gemini-primary path first (resolve + objective-validate + preserve its order/reasons) and falls back to the deterministic candidate-build → exclude → score → top-N pipeline when that path yields nothing usable. `start_session`/`answer_session` require `user_id`: sessions are owned and checked the same way library entries are; completed/dropped exclusion and the Gemini taste-context summary are both scoped to the calling account only |
| **Scoring** | movie/series weighted score; book genre + mood-tag overlap (spec §9.1/9.2) — the deterministic fallback path only; not computed at all for a successful Gemini-primary result |
| **Gemini pipeline** | title resolution against the data-API clients (title/year confidence match, discards unresolved/unconfident suggestions); objective-only validation (language, media type, rating, release period, the calling account's own collection-exclusion, quality floor) — deliberately never genre (spec §9.0.2) |
| **LLM client** (provider-agnostic) | one bounded JSON call per turn: structured preference object (spec §7) **and** the semantic candidate-title list with reasons — the primary recommendation source, not extraction-only. A second, separate bounded call type for the optional `mood_tags` classification (spec §6.4). Gemini provider, swappable; absent or failed → fully deterministic fallback |
| **Availability service** | watch-provider lookup + "unknown" fallback; book link passthrough or clean omission (spec §5.4) |

Holds all secrets, including the JWT signing key. Applies DB migrations on
deploy.

### 2.3 Database — Postgres

Tables per spec §6.1: `user` (accounts), `media_item` (shared/global cache,
never user-owned), `library_entry` (user-owned, `user_id` not null),
`series_progress` (owned via its 1:1 `library_entry` FK — no separate
`user_id`), `taste_profile` (one row per account, `user_id` is the primary
key), `recommendation_session` (user-owned, `user_id` not null). Ownership
mirrors spec §6:

```
user ─┬─▶ library_entry ─▶ series_progress
      ├─▶ taste_profile
      └─▶ recommendation_session

media_item ◀── library_entry   (shared/global; many accounts may reference the same row)
```

Must survive redeploys (spec §13).

### 2.4 External services

- **TMDb** — movie/series search/discover, metadata, watch providers (IN);
  also resolves Gemini-suggested titles.
- **Open Library / Google Books** — book search and metadata; also resolves
  Gemini-suggested book titles.
- **LLM provider — Google Gemini, behind a provider-agnostic interface.**
  Bounded JSON calls only. The primary call both extracts the structured
  preference object *and* returns the semantic candidate list with reasons.
  A separate, second bounded call type for the optional `mood_tags`
  classification on add. Optional throughout: the engine runs without it via
  a fully deterministic fallback. No Anthropic dependency.

---

## 3. Data Flow

### 3.1 Registration & login

```
FE  ──POST /auth/register {email, password}──▶ BE
                             BE: hash password, create user row
FE  ◀── created account ──── BE

FE  ──POST /auth/login {email, password}──▶ BE
                             BE: verify credentials, issue JWT
FE  ◀── {access_token} ────── BE
FE: store token; attach `Authorization: Bearer <token>` to every subsequent
    request
```

### 3.2 Search & add

```
FE  ──GET /search?q&type──▶  BE                     (public, unauthenticated)
                             BE ──▶ TMDb / Book API ──▶ raw payloads
                             BE: normalize → common media shape
FE  ◀── normalized results ── BE

FE  ──POST /library {source, source_id, type}──▶ BE   (requires bearer token)
                             BE: upsert shared media_item (cache raw_metadata)
                             BE ──▶ LLM (provider-agnostic): classify mood_tags
                                    (bounded, one-shot; skipped if no provider)
                             BE: insert library_entry owned by the caller
                                 (status defaults to "want")
FE  ◀── created entry ────── BE
```

### 3.3 Library management

```
FE  ──PATCH /library/{id} {status|rating|review|favourite}──▶ BE
FE  ──PUT   /library/{id}/progress {season, episode}────────▶ BE   (series only)
                             BE: verify caller owns {id} (single ownership check)
                             BE: write library_entry / series_progress
                             BE: recompute the caller's own taste_profile
                                 (on status or rating change)
FE  ◀── updated entry ────── BE
```

### 3.4 Recommendation (full flow, spec §8.1, Gemini-primary architecture)

```
FE  ──POST /recommendations {request}──▶ BE            (requires bearer token)
     BE: create session owned by the caller (state = extracting)
     BE ──▶ Gemini (provider-agnostic, bounded, JSON): free text →
            (a) structured preference object (spec §7)
            (b) semantically-judged candidate title list with reasons (§9.0)
            └─ on failure / timeout / no provider → deterministic
               keyword+vocabulary parser produces the preference object only
     BE: for each Gemini-suggested title — resolve against a real provider by
         name/year with a confidence check (§9.0.1); discard unresolved or
         unconfident suggestions
     BE: objective-validate each resolved candidate — language, media type,
         rating, release period, the caller's own completed/dropped
         exclusion, quality floor (§9.0.2) — never genre
     ├─ Gemini path yields ≥1 valid candidate ─────────────────────────┐
     └─ Gemini unavailable, empty, or nothing survives validation:     │
          BE: sparsity check (spec §8.3) on the preference object      │
             ├─ sufficient ──────────────────────────────┐             │
             └─ sparse:                                   │             │
                  BE: state = needs_clarification           │             │
                  FE ◀── { question } ── BE                  │             │
                  FE ──POST /recommendations/{id}/answer──▶ BE             │
                  BE: re-extract from answer, merge, clarification_used = true
                                                            ▼             │
          BE: build candidate queries from preference object              │
          BE ──▶ TMDb / Book API: fetch candidates                        │
          BE: exclude caller's own completed/dropped; hard-filter `avoid` │
          BE: read caller's own taste_profile from DB                     │
          BE: score (spec §9.1 movies/series | §9.2 books); novelty term  │
                                                            │              │
                                                            ▼              ▼
     BE: state = ranking → take top N (default 8); preserve Gemini's own
         order/reasons on the primary path, or the deterministic score's
         order + templated reason on the fallback path
     BE ──▶ TMDb watch providers (IN) per movie/series result; book link
            passthrough
     BE: state = results
FE  ◀── ranked list [ item + reason + availability ] ── BE
```

**Invariants the orchestrator must enforce:** `awaiting_answer` entered at
most once per session (`clarification_used`); `ranking` always yields a
non-empty list unless every relevant data API is down (→ `error`); candidate
generation, scoring, ranking, and reason text on the **fallback** path never
route through the LLM; the single clarifying question is always
template-produced on either path (spec §8.2).

### 3.5 Failure paths (spec NFR2)

- Any external call: timeout + retry-once + typed fallback. TMDb providers
  missing → "availability unknown". Book link missing → field omitted.
  Primary book API empty → Google Books fallback. Gemini failure / timeout /
  absent → deterministic preference extraction and, if nothing else, the
  fully deterministic candidate/score/rank pipeline.
- All data APIs unreachable → session `error` state with a user-visible,
  non-crashing message.

---

## 4. Implementation Phases

Each phase lists **deliverables** and **verification checkpoints**, mapped
to spec FR / NFR / §16 acceptance criteria (shown as `AC:`).

### Phase 0 — Live skeleton *(foundation)*

**Deliverables**
- Repo scaffold: FastAPI backend, Next.js frontend.
- Postgres provisioned; `DATABASE_URL` wired.
- Migration tooling; run-on-deploy hook.
- Backend `/health`; frontend loads and calls `/health` through the backend
  base URL.
- Env var plumbing for `TMDB_API_KEY`, book API key (if needed), the LLM
  provider key (`GEMINI_API_KEY`), and the auth signing configuration
  (`JWT_SECRET_KEY` / `JWT_ALGORITHM` / `JWT_EXPIRES_MINUTES`) — set in the
  deploy platform, absent from the repo and the client bundle.
- Both halves deployed to public URLs; CORS configured.

**Verification**
- [ ] Backend public URL returns `/health` 200 and confirms a live DB
      connection.
- [ ] Frontend public URL renders and reaches the backend.
- [ ] `git grep` shows no keys committed; built client bundle contains no
      keys (`AC:` no hardcoded keys).

### Phase 1 — Data model & external ingestion

**Deliverables**
- Migrations for the full entity set (spec §6.1): `user`, `media_item`,
  `library_entry` (owned, `user_id` not null), `series_progress` (owned via
  its 1:1 `library_entry` FK), `taste_profile` (`user_id` as primary key),
  `recommendation_session` (owned, `user_id` not null). Ownership is
  designed in from the start.
- TMDb client: search, details, watch providers (region IN), including
  per-season episode counts.
- Book client: Open Library search + details; Google Books fallback (may be
  deferred to Phase 8 to keep this phase small — D1 permits single-API
  operation until then).
- Normalization layer → common `media_item` shape, including
  `length_bucket` mapping and `season_episode_counts` (spec §6.1, §6.4).

**Verification**
- [ ] Unit tests: normalization for a movie, a series, a book (field
      coverage, bucket thresholds, per-season counts).
- [ ] Integration smoke: live search for each type returns normalized
      items.
- [ ] Watch-provider fetch returns providers for a known title and the
      "unknown" sentinel for one with no IN data.
- [ ] Full migration chain applies cleanly to an empty database.

### Phase 2 — Authentication & account foundation *(end-to-end vertical slice)*

**Deliverables**
- Backend: `User` model (UUID PK, unique normalized email, bcrypt-hashed
  password); `POST /auth/register`; `POST /auth/login` (JWT, HS256,
  configurable expiry, no insecure default signing key); `get_current_user`
  dependency (401 on any invalid/missing/expired token or a user id that no
  longer exists).
- Frontend: login/register pages; token storage; the `Authorization:
  Bearer` header attached at the API client's single request function (the
  one choke point every API call goes through); route guarding for pages
  that require a session; logout.
- No other table is touched yet — this phase only establishes the
  account/auth primitive both sides of the stack build on next.

**Verification**
- [ ] A person can register, log in, and receive/store a working token
      (`AC:`, FR1).
- [ ] Every `get_current_user` failure mode (missing token, malformed,
      wrong signature, expired, deleted user) returns 401.
- [ ] A logged-in session persists across a page reload and is cleared on
      logout.
- [ ] Duplicate-email registration is rejected (409); password is never
      returned in any response.

### Phase 3 — User-owned library

**Deliverables**
- Backend: `POST/GET /library`, `GET/PATCH/DELETE /library/{id}` all
  require `get_current_user` and are scoped to `current_user.id`;
  `get_entry` is the single ownership choke point every mutation routes
  through — a different account's entry behaves identically to a
  nonexistent one. `unique(user_id, media_item_id)` lets the same shared
  `media_item` be referenced by any number of accounts' own entries.
- Frontend: search page + results, add-to-library, library list with
  status/type filters, item detail with status / rating slider / review /
  favourite — operating on the authenticated account's own library via the
  token wired up in Phase 2.
- `mood_tags` classification call fires on `POST /library` (spec §6.4, D6).

**Verification**
- [ ] Add a movie, a series, and a book to the library (`AC:`, FR2).
- [ ] Set status, rating, review, favourite on each of the three types
      (`AC:`, FR3).
- [ ] An unauthenticated request to any `/library*` route is rejected
      (FR1, FR11).
- [ ] Two accounts can each add the same title; both succeed, both
      reference the same shared `media_item` row, and each account's list
      shows only its own entry (`AC:` multi-user).
- [ ] Account A cannot GET/PATCH/DELETE account B's entry — identical
      404 to a nonexistent id (`AC:` multi-user, FR11).

### Phase 4 — Series progress (season-aware)

**Deliverables**
- `series_progress` writes via `PUT /library/{id}/progress`, scoped by the
  same ownership check as `library_entry` (no separate `user_id` needed —
  inherited through the 1:1 FK).
- Season-aware validation: current season/episode constrained to the
  series' real seasons and that season's real episode count (from cached
  `season_episode_counts`); season 0 ("Specials") excluded from
  selection/validation; legacy/uncached entries skip bound-checking rather
  than fabricating counts (spec §5.1).
- `seasons_completed` is server-derived (`= max(current_season - 1, 0)`)
  whenever `current_season` is supplied, never independently client-set in
  that request.
- Automatic rollover: advancing past a season's final episode moves to the
  next season's episode 1; advancing past the final episode of the final
  season offers "mark completed" instead of inventing a season.
- Frontend: progress editor built against real per-season data; hides when
  status is `completed`, restores exactly when reverted to `in_progress`.

**Verification**
- [ ] Track season/episode progress on a series (`AC:`).
- [ ] An episode/season number outside the known range is rejected
      server-side regardless of what the UI allows.
- [ ] Rollover at a season boundary and at the final season's final
      episode behave as specified.
- [ ] `seasons_completed` never disagrees with `current_season` after an
      update that sets the latter.

### Phase 5 — Taste profile & personalization

**Deliverables**
- Per-account `taste_profile`: `favourite_genres`, `favourite_languages`,
  `avg_rating_by_genre`, `avg_rating_by_language`, `completion_rate`,
  `drop_patterns` (spec §6.3).
- Recompute hooked into every status change and every rating change,
  scoped to the account that made the change; `user_id` is the primary
  key, so a second row for the same account is structurally impossible.

**Verification**
- [ ] Unit tests: profile fields correct over a seeded library.
- [ ] Changing a rating or status triggers recompute for that account only
      (FR10).
- [ ] Two accounts with different libraries produce independently correct
      profiles; one account's changes never alter another's cached profile
      (`AC:` multi-user).

### Phase 6 — Recommendation engine (Gemini-primary, single-turn)

**Deliverables**
- Provider-agnostic LLM interface: one bounded call, low token cap,
  JSON-only response, one short timeout, at most one retry — returns both
  the structured preference object (spec §7) and a bounded list of
  semantically-judged candidate titles with reasons (spec §9.0).
- Title resolution (hallucination guard, §9.0.1): each suggested title
  looked up by name/year against a real provider; unconfident/unresolved
  matches discarded.
- Objective validation (§9.0.2): language, media type, rating bound,
  release period, the calling account's own completed/dropped exclusion,
  and the shared minimum-quality floor — genre deliberately excluded
  (provider tags are too coarse to arbitrate semantic fit).
- Gemini's own ordering and reason text are preserved as-is on the primary
  path — no deterministic re-scoring.
- Deterministic fallback (§9.1 movies/series, §9.2 books): candidate
  generation from the preference object via the data APIs, hard filters
  (`avoid`, explicit rating/language/media_type, completed/dropped),
  weighted score with a rating-monotonic novelty term, templated
  per-result reason. Used whenever Gemini is unavailable, empty, or
  nothing it suggests survives resolution/validation.
- Availability attached to each result regardless of path (TMDb watch
  providers; book link passthrough or omission).
- `POST /recommendations` returns a ranked list directly (no clarification
  path yet — Phase 7).
- Frontend: recommendation request box + ranked results with reason and
  availability.

**Verification**
- [ ] A free-text request returns a ranked list with request-specific
      reasons (`AC:`, FR4, FR5, FR7).
- [ ] With the LLM provider disabled, the same request still returns a
      ranked list via the deterministic fallback — no error, no empty
      list.
- [ ] The LLM call is bounded and never invoked during fallback-path
      scoring/ranking/reason text (assert via call spies/logs).
- [ ] "Not highest-rated" test (spec §9.3): a request whose mood/tone
      conflicts with the top-rated candidate does not rank it #1, on both
      paths.
- [ ] A Gemini-suggested title that fails resolution or objective
      validation never reaches the result list.
- [ ] Availability shows for movies/series with provider data, "unknown"
      otherwise; a book link shows only when available (`AC:`, FR8).
- [ ] Marking a title `completed`/`dropped` in account A's library
      excludes it from account A's recommendations but not account B's
      (`AC:` multi-user).
- [ ] Account A's and account B's Gemini taste-context strings never
      contain each other's genres/languages/drop-patterns (`AC:`
      multi-user).
- [ ] Response time within the ~8 s demo target on a warm backend (NFR5);
      the fallback path is near-instant.
- [ ] `git grep` / built bundle: no LLM keys client-side (FR9).

### Phase 7 — Clarification flow (multi-turn)

**Deliverables**
- `recommendation_session` state machine (spec §8.1): `extracting →
  needs_clarification → awaiting_answer → ranking → results`, plus
  `error`. Every session is created by, and belongs to, exactly one
  authenticated account (spec §6.1) — `start_session` requires `user_id`;
  `answer_session` checks ownership through the same choke-point pattern
  as `library_entry`.
- Sparsity rule (spec §8.3): the 4-condition sufficiency test, including
  "Gemini already returned a usable suggestion."
- `POST /recommendations/{id}/answer`: re-extract, merge (new non-null
  wins; `avoid` union), set `clarification_used = true`.
- The clarifying question is chosen deterministically from a small
  templated set keyed on missing richness fields — no LLM call.
- One-question invariant enforced by `clarification_used`.
- Fallback when still sparse at ranking time (taste-profile-only for
  movies/series; popularity-within-favourite-genres for books).
- Frontend: render the single question when present, then the list.

**Verification**
- [ ] Sparse request → exactly one question → ranked list (`AC:`, FR6).
- [ ] Rich request, or one where Gemini already suggested usable titles →
      ranked list with no question (`AC:`).
- [ ] No session ever emits a second question, including when the answer
      is empty/declined (`AC:`).
- [ ] Account A cannot answer account B's session — identical 404 to a
      nonexistent session id; account B's own answer still succeeds
      (`AC:` multi-user, FR11).

### Phase 8 — Robustness & completeness

**Deliverables**
- Google Books fallback wired into the book client (D1), if not already
  done in Phase 1.
- `mood_tags` classifier on the shared provider-agnostic LLM interface,
  feature-gated and non-blocking.
- Error/timeout handling across all external calls; typed fallbacks per
  §3.5.
- Availability polish: consistent "unknown" state; clean book-link
  omission.
- `drop_patterns` / per-genre completion refinement in the scoring penalty
  if not already complete.
- Remove placeholder content; eliminate console/runtime errors; mobile +
  desktop viewport pass.

**Verification**
- [ ] Induced API failure (bad key / forced timeout) surfaces no unhandled
      error (NFR2).
- [ ] No console or runtime errors during a full walkthrough (NFR4).
- [ ] No placeholder/lorem content anywhere (NFR3).
- [ ] Layout correct at mobile and desktop widths (NFR1).
- [ ] Book purchase/access link appears only when the API returns one
      (`AC:`).

### Phase 9 — Acceptance testing & multi-user verification

**Deliverables**
- Full spec §16 acceptance checklist run against the deployed app,
  including the Multi-user / isolation cluster.
- A concrete two-account adversarial pass, covering:
  1. Both accounts can reference the same `media_item`.
  2. Each has an independent `library_entry` for it.
  3. Each sees only their own library.
  4. Each can independently set status/rating/review/favourite/progress on
     their own entry.
  5. Taste profiles are independently correct.
  6. Recommendation completed/dropped exclusions are independent.
  7. Recommendation taste-context is independent.
  8. Account A cannot retrieve or mutate account B's library entry, series
     progress, taste profile, or recommendation session by changing an id.
  9. A recommendation session belongs to exactly one account and cannot be
     answered by another.
- Secret audit: no keys or the JWT signing secret in repo history or
  client bundle (FR9).
- Migration idempotency confirmed across a clean redeploy.

**Verification**
- [ ] Every box in spec §16 checked on the deployed app, including every
      multi-user item.
- [ ] Fresh redeploy preserves data and applies migrations cleanly.

### Phase 10 — Deployment hardening & final gate

**Deliverables**
- Production environment/secrets configuration finalized (§6 below).
- CORS restricted to the deployed frontend origin.
- Production smoke test: register, log in, search, add, rate, request a
  recommendation, log out — on the live URLs.
- Demo script / seed library for review.

**Verification**
- [ ] Full smoke test passes against the live public URLs.
- [ ] `AC:` §16 checklist re-confirmed on the final deployed build.

---

## 5. MVP vs. Deferrable

### Must-have for the MVP deploy (Phases 0–6)

- Live frontend + backend + Postgres, no secrets client-side.
- Registered accounts, authenticated end-to-end (frontend token wiring
  included) — not deferred, since ownership enforcement is foundational to
  every other feature below it.
- Search movies/series (TMDb) and books (Open Library); add to one's own
  library; set status/rating/review/favourite; season-aware series
  progress.
- Per-account taste profile recomputed on rating/status change.
- Single-turn natural-language recommendation via the Gemini-primary
  architecture with a deterministic fallback, demonstrably not
  "highest-rated first," personalized and exclusion-scoped to the
  authenticated account.

### Required for final acceptance, but deferrable past the first deploy (Phases 7–9)

- The one clarifying-question turn and the full session state machine
  (spec §8) — the flagged complexity risk, so it follows a working
  single-turn engine rather than blocking it.
- Google Books fallback, if not already done in Phase 1.
- Error-handling hardening, "unknown"/omission polish, mobile pass,
  placeholder and console-error cleanup.
- The full acceptance-checklist pass, including the multi-user adversarial
  suite.

### Can be cut entirely only if scope must be reduced

- Google Books fallback (D1 default explicitly permits a single book API).
- Nothing else — every remaining item maps to a spec §16 acceptance
  criterion.

### Not in this plan (spec §17)

Book page/percentage progress, full taste-profile scoring for books, social
features, streaming/hosting, unbounded clarification, a trained ML model,
cross-session history.

---

## 6. Deployment Steps

Split topology (spec §15 D2 default): backend + Postgres on Render/Railway,
frontend on Vercel.

1. **Provision Postgres**; capture `DATABASE_URL`.
2. **Backend service:**
   - Env vars: `DATABASE_URL`, `TMDB_API_KEY`, book API key (if needed),
     `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `JWT_SECRET_KEY`,
     `JWT_ALGORITHM`, `JWT_EXPIRES_MINUTES`, `FRONTEND_ORIGIN`. The backend
     must boot and serve recommendations even with the LLM key absent; it
     must refuse to sign or verify tokens (not silently fall back to an
     insecure default) if the JWT signing key is absent.
   - Deploy hook runs DB migrations, then starts the app.
   - Expose `/health` (app + DB check).
3. **Frontend (Vercel):** single public env var for the backend base URL;
   confirm no secret env vars are exposed to the client.
4. **CORS:** backend allows only the deployed frontend origin.
5. **Smoke test** both public URLs (Phase 0 verification).
6. **Redeploy at each phase boundary;** re-run that phase's verification
   against the live URL.
7. **MVP deploy checkpoint** after Phase 6.
8. **Final hardening** (Phase 10): secret audit on repo + built bundle,
   clean-redeploy migration check, seed a demo library, full smoke test.

---

## 7. Risk-Driven Sequencing Notes

- **Deployment risk** is retired in Phase 0, before any feature work.
- **Cross-account data leakage** is the primary correctness risk introduced
  by the multi-user architecture — mitigated by a single ownership
  choke point per owned entity (§1, principle 8) and a dedicated adversarial
  verification pass in Phase 9, rather than scattered per-endpoint checks.
- **Conversation-state complexity** (spec §18) is isolated to Phase 7 and
  sits behind a working single-turn engine, so a slip there still leaves a
  demonstrable product deployed.
- **Book API coverage/quality varies.** Absorbed by shipping on Open
  Library alone first if needed and adding the Google Books fallback
  afterward.
- **LLM latency / unavailability** (spec §18, NFR5) is bounded three ways:
  the call is single-shot JSON with one short timeout; the fully
  deterministic fallback produces a complete result list with no network
  call whenever Gemini is slow, down, or returns nothing usable — a larger
  share of the overall risk than a simple extraction-only design would
  carry, since Gemini is the primary candidate source; and `mood_tags`
  stays a separate, optional, precomputed-on-add call.
- **Gemini hallucination / provider-tag unreliability** is bounded by never
  trusting Gemini for facts: every suggested title must resolve against a
  real provider with a title/year confidence check, and every objective
  constraint is verified against that provider's data — genre is the one
  deliberate exception, left to Gemini's own semantic judgment rather than
  an unreliable provider tag.
