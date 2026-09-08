# Personal Media Companion — Implementation Plan

| | |
|---|---|
| **Version** | 1.4 — marks Phase 8.3 (personalization/recommendation isolation) completed: `TasteProfile` is now per-account (old singleton discarded, not migrated) and `RecommendationSession` is user-owned for new sessions (legacy rows stay permanently NULL-owned by design); Phases 0-7 below are preserved as the historical record of what was actually built and are **not** rewritten to match the current architecture — see `spec.md` v1.4 for current behavior |
| **Date** | 2026-09-08 |
| **Basis** | `spec.md` (originally v1.0; current architecture is v1.4) |
| **Priority** | Get a working MVP deployed to a public URL early, then layer the rest on a live app |
| **Status** | Phases 0-7 and 7.5 complete and deployed; Phase 8.1, 8.2, and 8.3 code-complete and verified locally (production rollout of 8.2's and 8.3's migrations/route-enforcement not yet executed — see each phase's deployment sequencing); Phase 8.4 onward not yet started |

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
4. **The LLM call stays bounded** (spec §8.2, §9.0, §10): one request, low
   token cap, JSON-only structured output, one short timeout, at most one
   retry, no tools/multi-turn/agent loop. *(As originally written, this
   principle also confined the LLM to preference extraction only — that part
   is superseded by Phase 7.5: Gemini is now the primary source of the
   candidate list and reason text too, in that same one bounded call. What
   still holds unconditionally: the call is provider-agnostic, always sits
   behind a fully deterministic fallback, and never computes the weighted
   `score` of spec §9.1/9.2 itself.)* The only other LLM use anywhere is the
   optional `mood_tags` enrichment on add (spec §6.4) — a separate, equally
   optional, equally bounded call.
5. **Secrets server-side only** (spec FR8): the frontend talks only to the
   backend; all API keys are backend env vars.
6. **Follow the spec's open-decision defaults** (spec §15) unless a blocker
   forces otherwise: Open Library primary, split deploy, N = 8, weights
   0.50/0.35/0.15, slider rating input, `mood_tags` computed on add.
7. **No paid or personal-subscription runtime dependency.** The deployed app
   must run with no Anthropic access; the LLM provider is optional and
   swappable, and every LLM-touched feature has a deterministic path
   (spec §10, §18).

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
| **External clients** | TMDb client (search/discover, details, watch providers region IN); Book client (Open Library primary, Google Books fallback). Since Phase 7.5, `search`/discover-by-title is also used to resolve Gemini-suggested titles (spec §9.0.1), not only to build filtered candidate pools |
| **Normalization** | map provider payloads → common `media_item` shape (spec §6.1, §6.4 buckets); since Phase 7.5 also extracts `season_episode_counts` from the TMDb payload it already fetches |
| **Library service** | upsert `media_item`, create/update `library_entry` + `series_progress`; since Phase 7.5 also validates progress bounds and derives `seasons_completed` server-side (spec §5.1). Since Phase 8.2, every operation is scoped by a required `user_id`, with a single ownership choke point (`get_entry`) all mutations route through |
| **Taste-profile service** | recompute derived profile on every rating/status change (spec §6.3, FR9). Since Phase 8.3, one profile per account (`user_id` is the primary key) — `recompute`/`get_or_compute` both require it and only ever touch that account's own `library_entry` rows |
| **Recommendation orchestrator** | the session state machine (spec §8.1); sparsity rule (§8.3, now with a fourth "Gemini already has usable suggestions" condition). Since Phase 7.5, tries the Gemini-primary path first (resolve + objective-validate + preserve its order/reasons) and falls back to the original candidate-build → exclude → score → top-N pipeline only when that path yields nothing usable. Since Phase 8.3, `start_session`/`answer_session` require `user_id`: sessions are owned (checked in `answer_session` the same way `library.get_entry` checks entry ownership), the completed/dropped exclusion is per-account, and the Gemini taste-context summary is built from the caller's own profile only |
| **Scoring** | movie/series weighted score; book genre + mood-tag overlap (spec §9.1/9.2) — **fallback path only** since Phase 7.5; not computed at all for a successful Gemini-primary result |
| **Gemini pipeline** (new, Phase 7.5) | title resolution against the data-API clients (title/year confidence match, discards unresolved/unconfident suggestions); objective-only validation (language, media type, rating, release period, collection exclusion, quality floor) — deliberately never genre |
| **LLM client** (provider-agnostic) | one bounded JSON call per turn: structured preference object (spec §7) **and**, since Phase 7.5, the semantic candidate-title list with reasons — the primary recommendation source, not extraction-only. A second, separate bounded call type for the optional `mood_tags` classification (spec §6.4). Gemini provider (`gemini-3.5-flash-lite`), swappable; absent or failed → fully deterministic fallback |
| **Auth service** (Phase 8.1) | password hashing (`bcrypt`), JWT issuing/verification (`PyJWT`), register/authenticate; `get_current_user` FastAPI dependency. Since Phase 8.2, called by every `/library*` route via `Depends(get_current_user)` — no longer standalone |
| **Availability service** | watch-provider lookup + "unknown" fallback; book link passthrough or clean omission (spec §5.4) |

Holds all secrets. Applies DB migrations on deploy.

### 2.3 Database — Postgres

Tables per spec §6.1: `media_item` (now includes `season_episode_counts`),
`library_entry`, `series_progress`, `taste_profile` (derived record, still a
single global row), optional non-durable `recommendation_session`, and (Phase
8.1) `user` — not yet referenced by any other table. Must survive redeploys
(spec §13).

### 2.4 External services

- **TMDb** — movie/series search/discover, metadata, watch providers (IN);
  also resolves Gemini-suggested titles (Phase 7.5).
- **Open Library / Google Books** — book search and metadata; also resolves
  Gemini-suggested book titles (Phase 7.5).
- **LLM provider — Google Gemini (`gemini-3.5-flash-lite`), behind a
  provider-agnostic interface.** Bounded JSON calls only. Since Phase 7.5, the
  primary call both extracts the structured preference object *and* returns
  the semantic candidate list with reasons — not extraction-only as
  originally scoped. A separate, second bounded call type for the optional
  `mood_tags` classification on add (spec §6.4). Optional throughout: the
  engine runs without it via a fully deterministic fallback, and `mood_tags`
  is simply skipped. No Anthropic dependency.

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
                             BE ──▶ LLM (provider-agnostic): classify mood_tags (bounded, one-shot; skipped if no provider)
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

> **Historical — describes the flow as Phase 4/5 built it.** Phase 7.5 made
> Gemini the primary source of the candidate list itself, with a title
> resolution + objective-validation step in place of "build candidate queries
> → score" on the primary path; the deterministic flow below is now the
> *fallback*, used as-is when Gemini is unavailable or nothing it suggests
> survives validation. See spec.md §8-9 for the current flow in full.

```
FE  ──POST /recommendations {request}──▶ BE
     BE: create session (state = extracting)
     BE ──▶ LLM (provider-agnostic, bounded, JSON): free text → preference object (spec §7)
            └─ on failure / timeout / no provider → deterministic keyword+vocabulary parser
     BE: sparsity check (spec §8.3)
        ├─ sufficient ────────────────────────────────┐
        └─ sparse:                                     │
             BE: state = needs_clarification           │
             FE ◀── { question } ── BE                 │
             FE ──POST /recommendations/{id}/answer──▶ BE
             BE ──▶ LLM: re-extract from answer (same deterministic fallback)
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
     BE: build one-sentence reason per result from the structured match
         explanation (template over matched sub-signals + one taste-profile fact) — no LLM
     BE ──▶ TMDb watch providers (IN) per movie/series result; book link passthrough
     BE: state = results
FE  ◀── ranked list [ item + score + reason + availability ] ── BE
```

**Invariants enforced in the orchestrator (as of Phase 5):** `awaiting_answer`
entered at most once per session; `ranking` always yields a non-empty list
unless all data APIs are down (→ `error`); candidate generation, scoring,
ranking, and reason text never route through the LLM. **As of Phase 7.5, the
last clause is true of the fallback path only** — see the note above.

### 3.4 Failure paths (spec NFR2)

- Any external call: timeout + retry-once + typed fallback. TMDb providers
  missing → "availability unknown". Book link missing → field omitted. Primary
  book API empty → Google Books fallback. LLM failure / timeout / absent →
  deterministic preference extraction (keyword match over our genre list,
  `MOOD_TAG_VOCABULARY`, length / intensity / period terms) or a
  client-supplied structured `preferences` object; ranking and reason text are
  deterministic and unaffected.
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
- Env var plumbing for `TMDB_API_KEY`, book API key (if needed), and the LLM
  provider key (`GEMINI_API_KEY`; `ANTHROPIC_API_KEY` optional) — set in the
  deploy platform, absent from the repo and the client bundle.
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

**LLM boundary (revised).** The only LLM use in the whole engine is turning the
user's free-text request into the structured preference object of spec §7.
Candidate retrieval, filtering, scoring, ranking, and the per-result reason
sentence are all deterministic backend code over our own media metadata and the
taste profile. The deployed app must work with no Anthropic access and no
personal subscription; the LLM provider is optional and swappable.

> **Superseded by Phase 7.5.** This was the correct description of the engine
> as Phase 4 originally shipped it, and everything below is preserved as that
> historical record — the `PreferenceExtractor` interface, the Gemini
> extraction provider, and the deterministic fallback described here all still
> exist in the codebase essentially as built. But the "LLM boundary" itself no
> longer holds: Phase 7.5 made Gemini the *primary* source of the candidate
> list and reason text too, not just the preference object. See spec.md §8.2,
> §9.0, §10 for the current architecture, and Phase 7.5 below for what
> changed and why.

**Deliverables**

- **Provider-agnostic LLM interface** — `app/services/llm/` with a
  `PreferenceExtractor` protocol exposing one method,
  `extract(request_text) -> PreferenceObject | None`. A single bounded call:
  low token cap, `temperature ≈ 0`, JSON-only response constrained to the
  spec §7 schema, one short timeout, at most one retry. No tools, no
  multi-turn, no agent loop.
- **Gemini provider** — the initial implementation, targeting a current
  free-tier model (`gemini-2.5-flash` at the time, overridable via
  `GEMINI_MODEL`; that model was later retired for this project's API
  key/tier and the default is now `gemini-3.5-flash-lite` — see Phase 7.5),
  using the API's structured-output mode (`response_mime_type=application/json`
  + response schema). Selected via an `LLM_PROVIDER` setting; `none` disables
  the LLM entirely.
- **Preference object** — a Pydantic model for spec §7, shared by the LLM
  path, the deterministic fallback, and the request body.
- **Deterministic extraction fallback** — used whenever the LLM is disabled,
  key-less, errors, or times out, and also directly callable:
  - `POST /recommendations` accepts an optional pre-structured `preferences`
    object; when present the LLM is skipped entirely.
  - otherwise a rule-based parser maps the free text onto the preference schema
    by matching our controlled vocabularies — the genre list, the fixed
    `MOOD_TAG_VOCABULARY` (spec §6.4), length words, intensity words, language
    names, and `recent` / `classic` — setting `explicit_fields` to whatever it
    matched literally.
  - the response reports which path produced the preferences (`llm` |
    `fallback`) for observability; behaviour is otherwise identical.
- **Candidate generation** from the preference object via the data APIs
  (TMDb / Open Library) — deterministic query building, no LLM.
- **Scoring** — movie/series weighted score (spec §9.1); book genre + mood-tag
  overlap (spec §9.2); novelty term; exclude `completed` / `dropped`;
  hard-filter `avoid`. Reads the Phase 3 taste profile. Fully deterministic.
- **Per-result reason** — a templated one-sentence string assembled from the
  structured match explanation (which sub-signals matched: genres, mood/tone,
  length, language, period) plus one taste-profile fact (e.g. mean rating for
  the matched genre, or a novelty note). Request-specific because it names the
  request's own matched fields. No LLM call.
- **Availability** attached to each result (TMDb watch providers, region IN;
  book link passthrough or clean omission).
- `POST /recommendations` returns a ranked list directly (no clarification
  path yet — that is Phase 5).
- **Config** — add `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`
  (server-side only, absent from the client bundle). `ANTHROPIC_API_KEY` stays
  optional and is not referenced by the recommendation engine.
- **Frontend**: recommendation request box + ranked results with reason and
  availability.

**Verification**
- [ ] A free-text request returns a ranked list with request-specific reasons
      (`AC:`, FR3, FR4, FR6).
- [ ] With `LLM_PROVIDER=none` (or no `GEMINI_API_KEY`) the same request still
      returns a ranked list via the deterministic fallback — no error, no empty
      list.
- [ ] Posting a pre-structured `preferences` object bypasses the LLM and yields
      the same shape of result.
- [ ] The LLM call is bounded — one request, JSON-only, low token cap, single
      short timeout — and is never invoked during candidate generation,
      scoring, ranking, or reason text (assert via call spies / logs).
- [ ] "Not highest-rated" test (spec §9.3): a request whose mood/tone conflicts
      with the top-rated candidate does not rank that candidate #1 (`AC:`) —
      holds regardless of extraction path, since scoring is deterministic.
- [ ] Movie/series results use the taste profile; book results use
      genre/mood-tag matching (`AC:`).
- [ ] Availability shows for movies/series with provider data, "unknown"
      otherwise (`AC:`, FR7).
- [ ] Reasons carry no lorem/placeholder text and reference the actual request
      fields — with the LLM off as well (`AC:` non-generic reason).
- [ ] Response time within the ~8 s demo target on a warm backend (NFR5); the
      fallback path is near-instant.
- [ ] `git grep` / built bundle: no LLM keys client-side (`AC:`).

> **▶ MVP DEPLOY CHECKPOINT** — after Phase 4, redeploy and confirm the full
> core loop works on the public URL. This is the earliest complete,
> demonstrable product.

### Phase 5 — Clarification turn  *(required for final acceptance; deferrable past the MVP deploy)*

**Deliverables**
- `recommendation_session` state machine (spec §8.1): `extracting →
  needs_clarification → awaiting_answer → ranking → results`, plus `error`.
- Sparsity rule (spec §8.3): the 3-condition sufficiency test.
- `POST /recommendations/{id}/answer`: re-extract (Phase 4 LLM interface + the
  same deterministic fallback), merge (new non-null wins; `avoid` union), set
  `clarification_used = true`.
- The clarifying question is chosen deterministically from a small templated set
  keyed on which richness fields are missing (spec §8.3) — no LLM call.
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
- Migrate the Phase 2 `mood_tags` classifier onto the shared provider-agnostic
  LLM interface (Gemini) so no code path requires Anthropic; it stays
  feature-gated and non-blocking.
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

### Phase 7.5 — Recommendation & progress architecture evolution  *(completed, post-Phase-7)*

Three related bodies of work, done after the original Phase 0-7 plan was
complete and deployed. Grouped here as one phase because they're
chronologically contiguous and touch the same two subsystems (the
recommendation engine and series progress) — see spec.md v1.1 for the
resulting current behavior in full detail; this section is the historical
record of *what changed and why*.

> **Naming note:** the repository's own git history has an earlier commit
> literally titled "Phase 8: hard constraints for rating + genre, romance
> intent, preview metadata" — an informal commit-message label written before
> "Phase 8" was reserved for multi-user work below. To avoid two unrelated
> things both being called "Phase 8" in this document, that work is folded
> into this Phase 7.5 instead, alongside the two later overhauls it preceded.
> Flagging this explicitly rather than silently renumbering it away.

**7.5.a — Hard constraints for rating, language, media type, and release
period.** Diagnosed and fixed one at a time: an explicit rating bound
(`PreferenceObject.rating`, spec §7) was added and made a hard filter; a
diagnosed bug where an explicit language constraint (e.g. "Telugu") could
still let a wrong-language candidate through was fixed by adding
`matches_explicit_language` as a real hard filter (an unresolved language name
is treated as unsatisfiable, never silently unrestricted); a novelty-scoring
defect that let a *lower* external rating outrank a higher one within an
otherwise-tied candidate group was fixed (rating now only ever pulls the
novelty term up, never down). "Romance"/"love story" was confirmed to already
be treated as genre content, not only mood.

**7.5.b — Gemini-primary recommendation architecture.** The single largest
change to the recommendation engine since Phase 4. Gemini went from
extraction-only to the primary source of the candidate list itself: one
bounded call now both extracts the preference object *and* returns a
semantically-judged list of title suggestions with reasons, using Gemini's own
knowledge rather than provider tags. New deterministic machinery was built
around it, never trusting Gemini for facts: title resolution against
TMDb/Open Library/Google Books with a title/year confidence check
(hallucination guard — an unresolved or unconfident suggestion is discarded),
and objective-only validation of language/media-type/rating/release-period/
collection-exclusion/quality-floor — deliberately **not** genre, since
provider genre tags were found too coarse to arbitrate semantic intent (a
correctly Telugu-language romantic drama can carry no "Romance" tag at all).
The pre-existing deterministic pipeline (candidate generation, weighted
scoring, ranking) was kept completely intact as the fallback for when Gemini
is unavailable or nothing it suggests survives resolution/validation — not
rewritten, reused as-is. Also fixed in this window: the Gemini model itself
(`gemini-2.5-flash` was retired for this project's API key/tier; the
"obvious" replacement Google's own error suggested, `gemini-3.6-flash`, turned
out to be a slower "thinking" model whose reasoning tokens ate the response
budget; `gemini-3.5-flash-lite` — the current default — has no such overhead).
See spec.md §5.3, §8.2, §9.0-9.4, §10.

**7.5.c — Season-aware series progress.** The progress editor allowed
contradictory states (e.g. an episode number beyond a season's real episode
count). Fixed end-to-end: TMDb's per-season episode-count data (already
present in the metadata this app already fetched, but previously discarded)
is now parsed and cached as `media_item.season_episode_counts`; season 0
("Specials") is excluded from progress selection/validation the same way
TMDb's own season/episode totals already exclude it; `seasons_completed`
became a server-derived value (`= current_season - 1`) rather than an
independently-editable field, so it can no longer disagree with
`current_season`; an explicit "Advance" action rolls over from a season's
final episode to the next season's episode 1, and swaps to "mark completed"
at the final episode of the final season rather than inventing one; the
Progress UI hides entirely when status is `completed` and restores exactly
when reverted to `in_progress`; legacy entries with no cached per-season data
skip the new bound-checking rather than fabricating an episode count. See
spec.md §5.1, §6.1.

**Verification (as run at the time):** full backend test suite passing after
each of the three sub-changes; live verification against real TMDb data for
7.5.a/b (including the exact diagnosed "Telugu love story" case); live
verification of season rollover and the final-season boundary for 7.5.c
against a real multi-season title. No frontend changes in 7.5.a; frontend
progress-editor rewrite in 7.5.c passed `tsc --noEmit` and lint clean.

### Phase 8 — Multi-user architecture

Not part of the original spec v1.0 scope (which explicitly excluded
multi-user, spec §17 v1.0) — added as a new phase once single-user use was
validated in production. **8.1 and 8.2 are complete; 8.3-8.5 are not yet
started.** Full current-state detail (what's implemented vs. not yet wired)
is in spec.md §2, §6.1, §6.3, §13, §17 — this section is the phase breakdown
only.

#### 8.1 Authentication Foundation — **completed**

**Deliverables (all implemented)**
- `User` model: UUID primary key (consistent with every other table's PK
  convention), unique normalized (stripped + lowercased) email,
  bcrypt-hashed password, `created_at`. One additive Alembic migration —
  no other table touched.
- Password hashing via `bcrypt` directly (not `passlib`: unmaintained,
  known incompatibilities with recent `bcrypt` releases).
- JWT issuing/verification via `PyJWT`. Algorithm `HS256`. Default token
  lifetime 7 days (`JWT_EXPIRES_MINUTES`, configurable). Signing key
  (`JWT_SECRET_KEY`) has no default — a blank/predictable key is refused
  outright rather than silently signing with something insecure.
- `POST /auth/register` — email + password in, hashed before storage,
  duplicate email rejected with 409, password/hash never returned in any
  response.
- `POST /auth/login` — verifies credentials, returns a standard
  `{access_token, token_type: "bearer"}` JWT response on success, 401 on
  failure (the same error for "no such email" and "wrong password" — never
  reveals which one it was, so the error can't be used to enumerate
  registered emails).
- `get_current_user` FastAPI dependency — extracts + verifies the bearer
  token, loads the named user, 401 on any failure mode (missing token,
  malformed, wrong signature, expired, or a user id that no longer exists).
  Follows the existing `Depends(get_db)` pattern.
- Auth-specific request/response schemas, and 21 focused tests (registration,
  duplicate handling, hashing verified never-plaintext, login success/failure,
  and every `get_current_user` failure mode including expired tokens and a
  valid token naming a deleted user).

**Deliberately not done in 8.1 (by design, not oversight):**
- **No route protection anywhere yet.** `get_current_user` exists and is
  tested directly, but no library/taste-profile/recommendation endpoint
  requires it — every existing endpoint's behavior is completely unchanged.
- **No `user_id` on any other table.** `LibraryEntry`, `SeriesProgress`,
  `RecommendationSession`, `TasteProfile` are untouched.
- No frontend changes — no login UI, no token storage, no auth header.

**Verification (as run):** full backend suite passing (244/244 at the time,
223 prior + 21 new); Alembic migration round-trip verified (upgrade →
downgrade → upgrade, zero drift both ways); confirmed live against the
running dev server that every pre-existing endpoint (`/health`, `/library`,
`/docs`) behaves identically, and that `/auth/register` works end-to-end.

#### 8.2 Library Ownership — **completed**

**Deliverables (all implemented)**
- `LibraryEntry.user_id` (FK → `user.id`, `ON DELETE CASCADE`, `NOT NULL`).
  Split across two Alembic migrations rather than one, specifically so
  pre-existing rows never get assigned to an invented account:
  - `47cf8fa2576e` — adds `user_id` **nullable**, adds the FK, and swaps the
    unique constraint (below) immediately. Pure additive DDL, no data
    written — safe on both an empty database and one with existing rows
    (every existing row simply becomes `user_id IS NULL`).
  - `1c240902dee9` — tightens `user_id` to `NOT NULL`. Meant to be deployed
    only once every pre-existing row has been claimed by a real account (see
    the script below); if any row is still `NULL` when it runs, the
    `ALTER COLUMN ... SET NOT NULL` fails and the deploy stops — verified
    directly (a scratch database with one deliberately-unclaimed row: the
    migration raised `IntegrityError` and left the column nullable, no
    partial state). That failure is intentional: it forces the claim step
    to be completed first instead of silently inventing an owner for
    whatever's left.
  - `app/scripts/claim_legacy_library.py` (new, following the existing
    `app/scripts/backfill_mood_tags.py` one-off-script convention) —
    assigns every row still at `user_id IS NULL` to a real, already
    -registered account, looked up by `--email` (or auto-selected if
    exactly one user exists). Run once, manually, between the two
    migrations above, after registering the real owning account via
    `POST /auth/register`. Idempotent: a second run finds nothing left to
    claim. Verified end-to-end against the local dev database: registered a
    real user, ran the script (`--dry-run` then for real) against 7
    pre-existing rows, confirmed all 7 were reassigned and zero remained
    `NULL`, then applied `1c240902dee9` successfully.
  - This design deliberately replaces an earlier draft of `47cf8fa2576e`
    that backfilled to the earliest-registered user or, if none existed,
    created a permanent placeholder account (`owner@media-companion.local`)
    with an unrecoverable random password — discovered during review to be
    a dead end: nobody could ever log into that account to "become" it, so
    reassigning its data still required a manual fix afterward anyway. The
    two-migration-plus-script design gets the same safety (never blocks on
    a missing user, never fails outright) without ever minting an account
    nobody can access.
  - No pre-existing `library_entry` or `series_progress` row was lost or
    altered beyond gaining an owner; `media_item` is never touched by any of
    this.
- Replaced `library_entry`'s global `unique(media_item_id)` with composite
  `unique(user_id, media_item_id)` — the same account still can't add a title
  twice (409, unchanged), but two different accounts can each hold their own
  entry for the same title, always pointing at the same shared `media_item`
  row (never duplicated — `_get_or_create_media_item` already deduplicated on
  `(source, source_id)` before this phase and is untouched).
- `services/library.py` — every operation (`add_to_library`, `list_entries`,
  `get_entry`, `update_entry`, `remove_from_library`, `update_progress`)
  takes a required `user_id` and is scoped by it. `get_entry` is the single
  ownership choke point every mutation routes through: an entry that exists
  but belongs to a different account raises the identical `EntryNotFound` as
  one that doesn't exist at all — ownership and non-existence are
  indistinguishable from the API's point of view, by design (spec §6.1).
- `api/library.py` — `Depends(get_current_user)` added to all six routes
  (`GET/POST /library`, `GET/PATCH/DELETE /library/{id}`,
  `PUT /library/{id}/progress`); every service call now passes
  `user_id=current_user.id`. An unauthenticated request 401s before any
  handler body runs. Search and media-details endpoints were **not**
  touched — they stay stateless and unauthenticated, as before.
- `SeriesProgress` needed no separate `user_id`, confirming the Phase 8.1
  plan's assumption: it inherits scope automatically from its 1:1,
  cascade-deleted parent `LibraryEntry` — verified directly by a cross-user
  progress-isolation test, not just assumed.
- Tests: `tests/conftest.py`'s `client` fixture now auto-registers and logs
  in a default user, attaching the bearer token to every request that
  fixture's `TestClient` instance makes — this kept all ~80 pre-existing
  `/library` call sites across `test_library_api.py`,
  `test_gemini_recommend.py`, `test_recommendations.py`, and
  `test_taste_profile.py` passing unchanged, without editing them
  individually. A `register_and_login()` helper mints a second, distinct
  authenticated identity for isolation tests via per-call header overrides.
  New coverage added to `test_library_api.py`: unauthenticated 401 on every
  library route; authenticated success; account A cannot GET/PATCH/DELETE
  account B's entry or PUT its progress (404, not a different status —
  confirms the no-existence-leak design); same-account duplicate still 409;
  different accounts adding the same title both succeed and reference one
  shared `media_item`; each account's list only shows its own entries;
  removing one's own entry still works once a second account also holds an
  entry for the same title.

**Deliberately not done in 8.2 (Phase 8.3, not this phase):**
- `TasteProfile` and `RecommendationSession` remain unscoped — recommendation
  ranking and the derived taste profile still draw on every account's
  `library_entry` rows, not just the caller's.
- No frontend changes — the frontend does not yet send an `Authorization`
  header, so it cannot successfully call any `/library` endpoint once route
  enforcement is actually deployed (see below — not yet).

**Deployment sequencing (important, not yet done):** `api/library.py`'s
`Depends(get_current_user)` is implemented and tested, but deploying it to
production *now* would 401 every request the live frontend makes, since the
frontend has no way to attach a bearer token until Phase 8.4. The plan is to
hold that specific piece — and only that piece — until it can ship in the
same release as 8.4's frontend token support:
1. Deploy `47cf8fa2576e` (nullable `user_id`) to production now — additive,
   invisible to the frontend, zero behavior change.
2. Register the real account via `POST /auth/register` against production
   (works standalone, no frontend needed).
3. Run `claim_legacy_library.py` once against production, pointed at that
   account; verify `SELECT count(*) FROM library_entry WHERE user_id IS
   NULL` is `0`.
4. Deploy `1c240902dee9` (`NOT NULL`) — safe now that every row is claimed.
5. Hold `api/library.py`'s auth requirement out of production until Phase
   8.4's frontend changes are ready to deploy alongside it in the same
   release.

**Verification (as run, local dev database):**
- Full migration chain applied cleanly to a fresh empty scratch database
  (`createdb` + `alembic upgrade head`), confirming both new migrations are
  safe no-ops with zero rows.
- `47cf8fa2576e` applied to the local dev database's 7 pre-existing
  `library_entry` / 2 `series_progress` rows: all 7 became `user_id IS
  NULL`, composite unique constraint confirmed via `\d library_entry`.
- `claim_legacy_library.py --dry-run` then for real, against a freshly
  registered test account: all 7 rows correctly listed and reassigned;
  re-running afterward correctly reported nothing left to claim.
- `1c240902dee9` applied afterward: succeeded, `alembic check` reported "No
  new upgrade operations detected" (zero drift).
- Failure-mode check: on a scratch database with one row deliberately left
  `user_id IS NULL`, `1c240902dee9` raised `IntegrityError` and left the
  column nullable — confirms the lock-down migration fails loudly rather
  than silently, and confirms the two-migration split actually does what
  it's meant to.
- Full deterministic backend suite re-run after the migration split: 254
  passed, 8 deselected (`test_clients_live.py`'s live-network tests,
  unrelated, gated behind `pytest -m integration`).
- `git diff` reviewed: `models/library.py`, both migrations,
  `services/library.py`, `api/library.py`, `tests/conftest.py`,
  `tests/test_library_api.py`, and the new `claim_legacy_library.py` script
  changed for this phase, plus this file and spec.md.

**Note on the local dev database used for verification above:** the 7 rows
it holds are development/test data from early Phase 1–2 work (five were
inserted within a single 6-second window — a scripted/batch insert, not
manual UI use — and the other two are same-day exploratory testing), not
the project owner's real production collection, which lives in a separate
Render-hosted database this session has not connected to. They were used
here only to exercise the migration and script against realistic non-empty
data; nothing about them is treated as data that must be preserved beyond
this verification.

#### 8.3 Personalization / Recommendation Isolation — **completed**

**Deliverables (all implemented)**
- `TasteProfile` converted from its fixed-singleton design (`SINGLETON_ID =
  1`, one row for the whole application) to one row per account: `user_id`
  (FK → `user.id`, `ON DELETE CASCADE`) **is the primary key itself** —
  "one profile per account" is a primary-key guarantee, not an
  application-level convention. `recompute()`/`get_or_compute()` both
  require `user_id` and query only that account's `library_entry` rows.
- Migration `2ae0cf36212a` performs the schema change. Since
  `taste_profile` is pure derived/cache data (never user-input, fully
  rebuildable from `library_entry`), and the pre-8.3 singleton row was
  computed from *every* account's library combined — it has no single real
  owner to assign it to — the migration **discards the existing row**
  (`TRUNCATE TABLE taste_profile`) rather than guess-assigning it, the same
  reasoning that led 8.2's migration away from inventing a placeholder
  owner. Each account's profile is rebuilt correctly, automatically, the
  first time `get_or_compute()` runs for them. Does **not** touch
  `library_entry` or `series_progress` in any way — verified directly (see
  Verification below).
- `RecommendationSession.user_id` (FK → `user.id`, `ON DELETE CASCADE`)
  added via migration `bee1a3183184`, **nullable permanently** — not a
  transitional nullable-then-NOT-NULL pair like 8.2's library migration.
  This table is documented debug/prunable data (spec §6.1, §8.4); every
  session created from 8.3 onward always gets a real `user_id`
  (`start_session` requires it), and pre-8.3 legacy rows are left `NULL`
  forever rather than backfilled via a claim script. No backfill, no
  placeholder account, nothing to reassign — a `NULL`-owned row can never
  match any authenticated caller's `user_id` in `answer_session`'s ownership
  check, so it simply becomes permanently unreachable through the API.
- `services/taste_profile.py` — `recompute`/`get_or_compute` both take a
  required `user_id` keyword. All 3 call sites in `services/library.py`
  (`add_to_library`, `update_entry`, `remove_from_library`) updated to pass
  the acting user's id — already available there since Phase 8.2.
- `services/recommendations/__init__.py` — `start_session` and
  `answer_session` both take a required `user_id` keyword.
  `start_session` sets it on the new `RecommendationSession`.
  `answer_session` checks it exactly like `library.get_entry` checks
  `LibraryEntry.user_id`: `if session is None or session.user_id != user_id:
  raise SessionNotFound(...)` — a wrong-owner session 404s identically to a
  nonexistent one, and (per this phase's explicit requirement) the session
  UUID's unguessability is *not* relied on as the only protection anymore.
  `_excluded_keys` (completed/dropped exclusion, spec §9) gained a required
  `user_id` and now filters `LibraryEntry.user_id == user_id` — previously
  global, so one account's watch history could hide or fail to hide titles
  for another account entirely by accident.
- `api/taste.py` (`GET /taste-profile`) and `api/recommendations.py`
  (`POST /recommendations`, `POST /recommendations/{id}/answer`) all gained
  `Depends(get_current_user)`, passing `current_user.id` through as
  `user_id`. Search and media-details endpoints untouched — still stateless
  and unauthenticated, per this phase's explicit scope.
- **Gemini personalization, not redesigned:** the existing Gemini-primary
  architecture (request → Gemini semantic recommendation → provider title
  resolution → deterministic objective validation → Gemini's own
  ordering/reasons preserved → deterministic fallback) is untouched. The
  only change is that `taste_context` (the background-context string
  summarized into the Gemini prompt, spec §9.0) is now always built from the
  *calling account's* `TasteProfile`, never a combined/global one — verified
  directly by asserting on the exact string content passed to a spy
  recommender (see Tests below).

**Deliberately not done in 8.3 (out of this phase's scope):**
- Phase 8.4 (frontend login/register/token support) and Phase 8.5
  (production QA/deploy) — untouched, as instructed.
- No claim script or backfill mechanism for `recommendation_session` — a
  deliberate design choice (see above), not an oversight.

**Deployment sequencing (not yet done — same pattern as 8.2):** the new
`Depends(get_current_user)` requirements on `GET /taste-profile`,
`POST /recommendations`, and `POST /recommendations/{id}/answer` are
implemented and tested, but — like 8.2's library route enforcement —
deploying them to production now would 401 every request the live frontend
makes to these endpoints, since the frontend still cannot attach a bearer
token. This enforcement is held until it can ship in the same release as
Phase 8.4's frontend token support, alongside 8.2's already-held library
route enforcement. The `2ae0cf36212a` and `bee1a3183184` migrations
themselves have no such constraint — they're pure schema/data changes,
invisible to the frontend, and can be deployed independently whenever
convenient.

**Tests added:** unauthenticated 401 on all three newly-protected routes;
two accounts with different libraries produce independent taste profiles
(different favourite genres/languages); one account's library changes leave
another account's cached profile provably unchanged; exactly one
`taste_profile` row per account (asserted directly against the table, not
just via the API); a newly created session records a non-null owner
(asserted directly against the table); account A cannot answer account B's
session (404) and account B's own answer still succeeds afterward; account
B can answer their own session normally; account A's completed title stays
excluded for account A but is NOT excluded for account B (the exact
Inception/User-A/User-B example from this phase's brief); a spy recommender
captures the literal `taste_context` string per call, proving account A's
call never contains account B's genres/languages/drop-patterns and vice
versa. Regression: all pre-existing recommendation, taste-profile, and
Gemini-pipeline tests updated only where they constructed a `TasteProfile`
object directly (`id=1` → `user_id=uuid.uuid4()`, a pure object-construction
change with no behavioral impact) or monkeypatched `recompute`'s old
zero-arg signature — every existing assertion is unchanged.

**Verification (as run, local dev database):**
- Both new migrations applied cleanly to the local dev database (7
  `library_entry` / 2 `series_progress` rows, 1 pre-existing singleton
  `taste_profile` row, 83 pre-existing `recommendation_session` rows at the
  time): `library_entry` and `series_progress` row counts **unchanged**
  before/after (7 and 2); `taste_profile` correctly emptied to 0 rows
  (singleton discarded); all 83 `recommendation_session` rows preserved,
  all with `user_id IS NULL` (no backfill attempted, as designed).
- Full migration chain applied cleanly to a fresh empty scratch database —
  both new migrations are no-ops with zero rows.
- Downgrade → re-upgrade round-trip verified against the local dev database:
  `library_entry`/`series_progress` counts unchanged throughout;
  `recommendation_session`'s 83 rows survived the round trip;
  `taste_profile`'s schema correctly reverted to the `id`-PK shape and back;
  `alembic check` reported zero drift both before and after.
- Full deterministic backend suite: 265 passed (254 baseline + 11 new
  Phase 8.3 tests), 8 deselected (`test_clients_live.py`'s live-network
  tests, unrelated).
- `git diff --check`: clean.

#### 8.4 Frontend Authentication — *upcoming*

- Login/register pages, token storage, and the `Authorization: Bearer`
  header added at `lib/api.ts`'s single `request()` function — already the
  one choke point every existing API call goes through, so this is expected
  to be a small, centralized change.
- Route guarding / auth-aware navigation.

#### 8.5 Multi-User QA / Deployment — *upcoming*

- Live/production cross-account isolation QA against real deployed accounts,
  once 8.4 gives the frontend a way to actually authenticate as two
  different accounts end-to-end. (The adversarial checks themselves — can
  account A read/modify/delete account B's library entry, progress,
  session, or taste profile — are already implemented and automated-tested
  in 8.2 and 8.3; this phase is about confirming the same holds true against
  the live deployment, not writing the checks for the first time.)
- Run the Phase 8.2 and 8.3 migrations against the real production database,
  and deploy the held-back route-enforcement changes from both phases
  alongside 8.4's frontend release (sequencing documented under 8.2 and 8.3
  above).

---

## 5. MVP vs. Deferrable

### Must-have for the MVP deploy (Phases 0–4)

- Live frontend + backend + Postgres on public URLs, no secrets client-side.
- Search movies/series (TMDb) and books (Open Library).
- Add to library; set status / rating / review / favourite; series
  season/episode progress.
- Taste profile (minimal) recomputed on rating/status change.
- Single-turn natural-language recommendation: preference extraction (LLM via a
  provider-agnostic interface — Gemini free tier — with a deterministic
  fallback) → deterministic scored, ranked list → templated per-result reason →
  availability, demonstrably not "highest-rated first".

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

Book page/percentage progress, full taste-profile scoring for books, social
features, streaming/hosting, unbounded clarification, trained ML model,
cross-session history. (Multi-user/login was originally on this list too —
Phase 8 above supersedes that: an authentication foundation now exists and
the library, taste profile, and recommendation sessions are all user-owned
in code (8.1, 8.2, 8.3), though the route enforcement for all three is held
back from production until Phase 8.4 ships frontend token support.)

---

## 6. Deployment Steps

Split topology (spec §15 D2 default): backend + Postgres on Render/Railway,
frontend on Vercel.

1. **Provision Postgres** on Render/Railway; capture `DATABASE_URL`.
2. **Backend service:**
   - Set env vars: `DATABASE_URL`, `TMDB_API_KEY`, book API key (if the chosen
     API needs one), `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`
     (`ANTHROPIC_API_KEY` optional), `FRONTEND_ORIGIN`. The backend must boot
     and serve recommendations even with the LLM key absent.
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
- **LLM latency / availability** (spec §18, NFR5) is bounded three ways: the
  call is single-shot JSON with one short timeout; the deterministic fallback
  (Phase 4/5's original engine) still produces a full result list with no
  network call whenever the provider is slow, down, or returns nothing
  usable — a larger share of the risk than originally scoped, since Phase 7.5
  made Gemini the primary candidate source rather than extraction-only, but
  the same fallback absorbs it; and `mood_tags` stays a separate, optional,
  precomputed-on-add call.
- **Gemini hallucination / provider-tag unreliability** (added risk, Phase
  7.5, not in the original spec §18) is bounded by never trusting Gemini for
  facts: every suggested title must resolve against a real provider with a
  title/year confidence check, and every objective constraint is verified
  against that provider's data — genre is the one exception, deliberately
  left to Gemini's own judgment rather than an unreliable provider tag.
```
