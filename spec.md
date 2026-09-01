# Personal Media Companion — Specification

| | |
|---|---|
| **Version** | 1.0 (supersedes draft v0) |
| **Date** | 2026-08-31 |
| **Owner** | lasyapriya@iisc.ac.in |
| **Status** | Approved for build |

---

## 1. Overview

Build a **single-user** personal media companion that unifies **movies, TV
series, and books** in one library and lets the user describe what they feel
like watching or reading in **natural language** — mood, situation, and
constraints — instead of selecting filters.

The system:

1. Infers a structured set of preferences from the free-text request.
2. Asks **at most one** clarifying follow-up, and only if the request is
   genuinely too sparse to act on.
3. Returns a **ranked** list of recommendations, each with a one-sentence,
   request-specific reason.

Recommendations are explicitly **not** a "highest-rated first" list.

---

## 2. Target User & Problem

A single user — the project owner. No accounts, no login in v0.

The user currently splits movie/series tracking and book tracking across
separate apps, and wants recommendations driven by *"what do I feel like right
now"* rather than static filters or top-rated lists.

---

## 3. Product Philosophy

- *"Don't make me search through hundreds of filters. Let me tell you what I
  feel like watching or reading, and understand me."*
- *"Keep my movies, series, and books in one place, regardless of where I
  normally consume them."*

**Not the goal:** cloning Netflix / Goodreads / IMDb / Letterboxd, social
features, streaming or hosting copyrighted content, or a from-scratch ML
recommender.

---

## 4. Scope for v0

| Area | Movies / Series | Books |
|---|---|---|
| Search & discover | Full (TMDb) | Full (Open Library / Google Books) |
| Library + status tracking | Full | Full |
| Ratings & reviews | Full | Full |
| Progress tracking | Seasons / episodes | **None** — status only |
| Recommendation matching | Full taste-profile scoring | **Lighter** — genre + mood-tag overlap only, no taste-profile weighting |
| Availability info | TMDb watch providers (region: IN) | Purchase/access link *if* the book API provides one; no guarantee |

Books are intentionally lighter in v0 given the added complexity of the
multi-turn conversation flow (Section 8). Deepen in a later cycle.

---

## 5. Core Features

### 5.1 Unified Media Library

- Add any searched item (movie, series, or book) to the library.
- **Status:** `want` · `in_progress` · `completed` · `dropped`.
- **Favourite** flag.
- **Personal rating:** 1–10, half-steps allowed (1.0, 1.5, … 10.0). Optional.
- **Review / notes:** free text. Optional.
- **Progress:** seasons / episodes for series only. Movies have no progress;
  books have status only (no page or percentage tracking in v0).

### 5.2 Media Discovery

- Search movies / series via **TMDb**; search books via **Open Library** or
  **Google Books** (one is primary, the other a fallback when the primary
  returns no result — final choice in Section 15).
- **Display fields:** title, type, poster/cover, synopsis, genre, language,
  year, external rating, plus:
  - movies — runtime;
  - series — seasons, episodes, episode runtime;
  - books — author, page count.
- No manual metadata entry. No scraping.

### 5.3 Conversational Natural-Language Recommendations (multi-turn)

- User describes mood / situation / constraints in free text.
- An **LLM** (provider-agnostic; Google Gemini initially) extracts a
  **structured preference object** (Section 7) from that free text — this is the
  LLM's only role in the flow.
- **Clarification rule:** if the extracted preferences are too sparse for a
  confident recommendation, the agent asks **exactly one** follow-up question,
  then proceeds regardless of the answer. Hard cap of one clarifying turn — no
  open-ended back-and-forth. Precise rule in Section 8.3.
- **Session state** (the request, any clarification Q&A, the extracted
  preference object) lives only for the duration of that recommendation
  session. No cross-session conversation history in v0.
- Final ranking combines extracted preferences with the taste profile
  (Section 6.3) via a weighted score for movies/series, or genre / mood-tag
  overlap for books.
- Each recommendation carries a **one-sentence reason** that references the
  actual request (e.g. *"you usually enjoy Korean romantic comedies and this
  has short, light episodes with a similar tone"*), assembled deterministically
  from the matched signals (Section 9.4) — not written by the LLM.
- Recommendations must **not** simply be the highest-rated items (Section 9.3).

### 5.4 Availability

- **Movies / series:** streaming/platform availability via TMDb watch
  providers, region = India. If no provider data exists, show
  **"availability unknown"** — never an error or a blank.
- **Books:** show a purchase/access link if the book API returns one;
  otherwise omit the field cleanly (no broken links, no placeholder text).

---

## 6. Data Model

Persistence is **Postgres**. Single-user instance, so there is no `users`
table and each real-world item has at most one library entry.

### 6.1 Entities

#### `media_item` — cached external metadata

| Field | Type | Notes |
|---|---|---|
| `id` | uuid, PK | internal id |
| `source` | enum `tmdb` \| `open_library` \| `google_books` | provider the record came from |
| `source_id` | text | provider's id |
| `type` | enum `movie` \| `series` \| `book` | |
| `title` | text | |
| `description` | text | synopsis |
| `genres` | text[] | normalised genre labels |
| `language` | text | primary language (ISO code or label) |
| `year` | int | release / publication year |
| `external_rating` | numeric | provider rating, normalised to 0–10; used only as a low-priority quality prior, never as a sort key |
| `artwork_url` | text | poster / cover |
| `runtime_minutes` | int, null | movies |
| `seasons` | int, null | series |
| `episodes` | int, null | series |
| `episode_runtime_minutes` | int, null | series |
| `author` | text, null | books |
| `page_count` | int, null | books |
| `mood_tags` | text[] | derived tone/mood tags (see 6.4); used for matching |
| `raw_metadata` | jsonb | full provider payload, for debugging and later fields |
| `fetched_at` | timestamptz | cache freshness |

**Constraints:** `unique (source, source_id)`.

#### `library_entry` — the user's relationship to an item

| Field | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `media_item_id` | uuid, FK → `media_item.id` | |
| `status` | enum `want` \| `in_progress` \| `completed` \| `dropped` | required |
| `favourite` | bool, default false | |
| `rating` | numeric, null | 1.0–10.0, constrained to 0.5 steps |
| `review` | text, null | |
| `added_at` | timestamptz | |
| `updated_at` | timestamptz | |

**Constraints:** `unique (media_item_id)`.

#### `series_progress` — series only

| Field | Type | Notes |
|---|---|---|
| `library_entry_id` | uuid, PK, FK → `library_entry.id` | |
| `seasons_completed` | int, default 0 | |
| `current_season` | int, null | |
| `current_episode` | int, null | |
| `updated_at` | timestamptz | |

Rows exist only for entries whose `media_item.type = 'series'`.

#### `recommendation_session` — optional, non-durable

The conversation is session-scoped (Section 8.4). A backend that cannot hold
state in memory MAY persist sessions here for statelessness and debugging, but
rows are **not** surfaced as user-visible history and MAY be pruned freely.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid, PK | session id returned to the client |
| `original_request` | text | |
| `preference_object` | jsonb | latest extracted preferences (Section 7) |
| `clarification_question` | text, null | the single question, if one was asked |
| `clarification_answer` | text, null | user's reply, if any |
| `clarification_used` | bool, default false | **invariant: once true, no further question may be asked** |
| `results` | jsonb, null | ranked recommendation payload |
| `state` | enum (Section 8.1) | |
| `created_at` | timestamptz | |

### 6.2 Enumerations

- `media_type`: `movie`, `series`, `book`
- `library_status`: `want`, `in_progress`, `completed`, `dropped`
- `source`: `tmdb`, `open_library`, `google_books`
- `length_bucket`: `short`, `medium`, `long` (mapping in 6.4)
- `intensity`: `low`, `medium`, `high`
- `session_state`: `extracting`, `needs_clarification`, `awaiting_answer`,
  `ranking`, `results`, `error`

### 6.3 Taste Profile (derived, not a trained model)

Recomputed on every rating change and every status change. Stored as a single
derived record (table or materialised view).

| Signal | Definition |
|---|---|
| `favourite_genres` | genres ranked by (count of `completed` + `favourite`) then by average rating |
| `favourite_languages` | languages ranked the same way |
| `avg_rating_by_genre` | map: genre → mean personal rating over rated items in that genre |
| `avg_rating_by_language` | map: language → mean personal rating |
| `completion_rate` | `completed` ÷ (`completed` + `dropped`), overall and per genre |
| `drop_patterns` | genres/languages with completion_rate below a low threshold |
| `computed_at` | timestamptz |

Used as a scoring input for **movie/series** recommendations. For **books** in
v0 it is used only as a light tiebreaker, if at all.

### 6.4 Derived tags & bucket mappings

- **`mood_tags`** on `media_item` are assigned at fetch time by a bounded,
  one-shot **LLM** classification call (provider-agnostic; see Section 10) from
  the synopsis + genres, drawn from a fixed vocabulary, e.g. `cozy`, `tense`,
  `feel-good`, `dark`, `bittersweet`, `slow-burn`, `high-energy`, `cerebral`,
  `escapist`, `romantic`, `bleak`, `wholesome`. The vocabulary is a constant in
  the codebase. This call is optional: with no LLM provider configured the field
  is left empty and backfilled later.
- **`length_bucket`** mapping:
  - movie: `<90 min` → short, `90–150` → medium, `>150` → long
  - series: episode runtime `<30 min` → short, `30–50` → medium, `>50` → long
  - book: `<250 pp` → short, `250–500` → medium, `>500` → long

---

## 7. Preference Object

The structured output the LLM (or the deterministic fallback, Section 8.3)
produces from the free-text request. All fields optional; absent fields are
`null` or `[]`.

```jsonc
{
  "media_type":    ["movie" | "series" | "book"] | null,  // null = any
  "mood":          string[],   // from the mood_tags vocabulary where possible
  "tone":          string[],   // "light", "dark", "bittersweet", "uplifting", ...
  "genres":        string[],
  "length":        "short" | "medium" | "long" | null,
  "intensity":     "low" | "medium" | "high" | null,
  "language":      string[],
  "release_period": { "from_year": int, "to_year": int } | "recent" | "classic" | null,
  "avoid":         string[],   // genres / themes / content to hard-exclude
  "explicit_fields": string[]  // which of the above the user stated outright
                               // (vs. inferred) — drives the sparsity check
}
```

`avoid` is always a **hard filter**, never a soft signal.

---

## 8. Conversational Recommendation Flow

### 8.1 State machine

```
                 ┌─────────────┐
   request  ──▶  │  extracting │
                 └──────┬──────┘
                        │  LLM (or fallback) returns preference object
              ┌─────────┴───────────┐
       sufficient?                sparse?  (rule 8.3)
              │                        │
              ▼                        ▼
        ┌──────────┐          ┌──────────────────┐
        │ ranking  │          │ needs_clarification│
        └────┬─────┘          └─────────┬─────────┘
             │                          │ emit ONE question
             │                          ▼
             │                 ┌──────────────────┐
             │                 │ awaiting_answer  │
             │                 └─────────┬────────┘
             │        answer OR "just recommend" OR timeout
             │                          │ re-extract, merge, set
             │                          │ clarification_used = true
             │                          ▼
             │                    ┌──────────┐
             └───────────────────▶│ ranking  │
                                  └────┬─────┘
                                       ▼
                                 ┌──────────┐
                                 │ results  │
                                 └──────────┘

  any state ──error──▶ ┌───────┐
                       │ error │  (graceful, user-visible fallback)
                       └───────┘
```

### 8.2 Hard invariants

- The `awaiting_answer` state is entered **at most once** per session.
  `clarification_used` guards it; once `true`, the flow can only go to
  `ranking`.
- `ranking` **always** produces a non-empty result list (falling back per
  8.3) unless the underlying APIs are all unavailable, which routes to
  `error`.
- Candidate generation (querying TMDb / book APIs), scoring, and ranking are
  driven by the preference object and the taste profile in deterministic
  backend code — **never** by the LLM. The LLM's **only** role is extracting the
  preference object from free text (Section 7), and it always sits behind a
  deterministic fallback (Section 8.3). The single clarifying question
  (Section 8.3) and every per-result reason (Section 9.4) are produced from
  templates over structured data, not by the LLM.

### 8.3 Sparsity rule (precise)

Let the **richness set** be the populated fields among:
`media_type, mood, tone, genres, length, intensity, language, release_period`.
(`avoid` does **not** count toward richness.)

Preferences are **sufficient** — proceed straight to `ranking` — if **any** of:

1. `genres` is non-empty; **or**
2. `mood` is non-empty **and** at least one of
   `{tone, media_type, length, language}` is populated; **or**
3. three or more fields in the richness set are populated.

Otherwise preferences are **sparse** → ask exactly one clarifying question. That
question is selected deterministically from a fixed templated set, keyed on
which richness fields are missing — no LLM call.

After the answer (or if the user declines / a short timeout elapses):
re-run extraction on the reply (LLM if available, deterministic parser
otherwise), **merge** into the existing preference object
(new non-null values win; `avoid` lists union), set `clarification_used = true`,
and go to `ranking` **unconditionally** — even if still sparse.

**Fallback when still sparse at ranking time:**

- movies/series → rank by taste profile alone (favourite genres × favourite
  languages × predicted rating), with the novelty term from 9.1 still applied.
- books → popularity within the user's favourite genres.

### 8.4 Session lifetime

- A session is created when a recommendation request is submitted and is
  addressable by `session.id` for the duration of that interaction.
- Nothing about the conversation needs to persist once results are delivered.
  Any persisted `recommendation_session` row is debug data and may be pruned.
- There is no "resume previous recommendation chat" feature in v0.

---

## 9. Recommendation Scoring

Candidates come from external-API queries built from the preference object
(genre filters, language, release window, type). The candidate pool
**excludes** any item whose `library_entry.status` is `completed` or
`dropped`, and **hard-excludes** anything matching `avoid`. Items already in
the library with status `want` are eligible.

### 9.1 Movies / series

```
score = w1 · preference_match
      + w2 · taste_profile_match
      + w3 · novelty_term
      − penalty
```

- **preference_match** — weighted overlap of: genres, mood_tags vs
  `mood`/`tone`, `length` bucket, `language`, `intensity`, `release_period`.
  Each sub-signal normalised to 0–1; weights are a tunable constant vector.
- **taste_profile_match** — genre affinity + language affinity + predicted
  personal rating from `avg_rating_by_genre` / `avg_rating_by_language`,
  normalised to 0–1.
- **novelty_term** — small positive weight for items that are *not* top-of-
  popularity / not top-`external_rating`, so the list cannot collapse to
  "most popular". 0–1.
- **penalty** — additive deductions for soft-avoid theme hits and for genres
  in the user's `drop_patterns`.

Suggested starting weights (tune during build): `w1 = 0.50`, `w2 = 0.35`,
`w3 = 0.15`. `external_rating` never enters the sort key directly — only as a
minimum-quality floor to drop obvious junk.

### 9.2 Books (v0, lighter)

```
score = genre_overlap + mood_tag_overlap
```

Both terms 0–1. Taste profile enters only as a tiebreaker
(`avg_rating_by_genre` where data exists). Same hard-exclusions and same
`avoid` filter as 9.1.

### 9.3 "Not highest-rated" guarantee

- The ranking sort key is `score`, never `external_rating` or `rating`.
- `external_rating` is capped to a low-weight quality floor only.
- **Acceptance test:** issue a request whose mood/tone deliberately conflicts
  with the highest-rated candidate; assert that candidate is not ranked #1.

### 9.4 Output

- Top **N** results (N in Section 15; default 8).
- Each result: the `media_item` display fields, the availability block
  (Section 5.4), the `score`, and a **one-sentence reason** assembled
  **deterministically** from the structured match explanation — a template over
  which sub-signals matched (genres, mood/tone, length, language, period) plus
  one taste-profile fact. Reasons must be request-specific, not generic;
  because the template names the request's own matched fields, this holds with
  no LLM call.

---

## 10. External APIs & Data Sources

| Source | Use |
|---|---|
| **TMDb** | movie/series search, metadata, watch providers (region IN) |
| **Open Library** *(primary)* or **Google Books** *(fallback / primary — 15)* | book search and metadata |
| **LLM provider** — Google **Gemini** initially (a current free-tier model), behind a provider-agnostic interface so it can be swapped | **Only** two bounded JSON calls: natural-language request → structured preference object (Section 7), and the optional `mood_tags` classification (Section 6.4). **Not** used for candidate generation, search, ranking, the clarifying question, or reason text. Always behind a deterministic fallback — the app is fully usable with **no LLM provider and no Anthropic access**. |

Keeping candidate generation on the data APIs bounds cost and latency; keeping
the LLM to one small extraction call with a deterministic fallback means the
deployed app never depends on paid or personal-subscription LLM access.

---

## 11. Functional Requirements

- **FR1** — User can search and add any movie/series/book to their library.
- **FR2** — User can set/change status, rating, review, and (series only)
  season/episode progress on any library item.
- **FR3** — User can submit a free-text recommendation request.
- **FR4** — System extracts a structured preference object from that request.
- **FR5** — System asks at most one clarifying question when preferences are
  sparse (rule 8.3), then always produces a recommendation list.
- **FR6** — Each recommendation includes a one-sentence, request-specific
  reason.
- **FR7** — System shows availability info, or a clean "unknown" state, for
  each recommended and viewed item.
- **FR8** — All external API keys are stored and used server-side only, never
  exposed to the frontend/browser.
- **FR9** — The taste profile is recomputed on every rating change and every
  status change.

---

## 12. Non-Functional Requirements

- **NFR1** — Works on desktop and mobile viewport widths.
- **NFR2** — Graceful handling of API failures / timeouts / missing metadata;
  no unhandled errors reach the user.
- **NFR3** — No placeholder / lorem-ipsum content in the delivered app.
- **NFR4** — No console or runtime errors during normal use.
- **NFR5** — A recommendation response, including any clarification
  round-trip, completes in a reasonable time for a live demo — target under
  ~8 s per turn under normal conditions. The deterministic fallback path has no
  LLM round-trip and is effectively instant.

---

## 13. Technical Architecture

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python) |
| Frontend | React / Next.js |
| Database | Postgres — persistence must survive redeploys; no local or in-memory-only storage |
| LLM | Provider-agnostic interface; Google Gemini (free-tier model) initially. Used only for request → preference extraction and the optional `mood_tags` call. Optional — a deterministic fallback keeps the engine working with no LLM access; no Anthropic / personal-subscription dependency |
| Auth | none — single-user instance |
| Deployment | backend + Postgres on Render or Railway; frontend on Vercel, or a single combined target (Section 15) |

---

## 14. Deployment Requirements

- A working **public URL**; no local-only functionality.
- Environment variables for **all** API keys (TMDb, book API, and the LLM
  provider — `GEMINI_API_KEY` initially). Never committed to the repo, never
  shipped to the client bundle. The backend must start and serve
  recommendations even when the LLM provider key is absent.

---

## 15. Open Decisions (resolve during implementation)

| # | Decision | Default if undecided |
|---|---|---|
| D1 | Book API: Open Library vs Google Books as primary | Open Library primary, Google Books fallback |
| D2 | Deploy topology: split (Render/Railway + Vercel) vs combined | split |
| D3 | `N` — number of recommendations returned | 8 |
| D4 | Scoring weight vector `w1/w2/w3` and sub-signal weights | 0.50 / 0.35 / 0.15 |
| D5 | Rating input widget granularity (slider vs 10 half-star clicks) | slider, 0.5 steps |
| D6 | Whether `mood_tags` classification is precomputed on add vs lazily on first recommendation use | on add |
| D7 | LLM provider + model for preference extraction | Google Gemini, a current free-tier model (e.g. `gemini-2.5-flash`), behind a swappable interface; deterministic fallback always present |

---

## 16. Acceptance Criteria (binary-checkable)

- [ ] Can search and add a movie, a series, and a book to the library.
- [ ] Can set status, rating, and review on each of the three media types.
- [ ] Can track season/episode progress on a series.
- [ ] A free-text recommendation request returns either (a) one clarifying
      question followed by a ranked list, or (b) a ranked list directly.
- [ ] The clarifying question is asked **at most once** — no session ever
      produces a second follow-up.
- [ ] Every recommendation shows a non-generic, request-specific reason.
- [ ] Recommendations are demonstrably not just "highest rated" — verified
      with a request where the top-rated candidate is a poor mood/tone match
      (test 9.3).
- [ ] Movie/series recommendations use the taste profile; book
      recommendations use genre / mood-tag matching (v0 scope).
- [ ] Availability info displays for movies/series with TMDb provider data,
      and shows a clean "unknown" state otherwise.
- [ ] Book purchase/access link shows only when the API returns one; no
      broken links or placeholder text otherwise.
- [ ] App is reachable at a public URL and works at desktop and mobile widths.
- [ ] No hardcoded API keys anywhere in the client bundle or repo.
- [ ] No placeholder content; no unhandled console/runtime errors.

---

## 17. Explicitly Out of Scope (v0)

- Book page / percentage progress tracking.
- Full taste-profile scoring for book recommendations.
- Multi-user accounts / login.
- Social features (sharing, following, messaging).
- Streaming or hosting media content.
- Open-ended (unbounded) conversational clarification.
- A trained / from-scratch ML recommendation model.
- LLM-generated candidate lists, ranking, or reason text — the LLM only
  interprets the request into structured preferences.
- Cross-session conversation history.

---

## 18. Known Risks

| Risk | Mitigation |
|---|---|
| Multi-turn conversation state adds real complexity — session handling and the exact one-question rule need precise logic. The main implementation-complexity risk in v0. | State machine and sparsity rule are fully specified (Sections 8.1–8.3); `clarification_used` is a hard invariant; fallback path guarantees a result. |
| Book API coverage/quality varies more than TMDb's. | Lighter v0 scope for books deliberately absorbs this; primary/fallback API pair (D1). |
| TMDb watch-provider data is region-specific and sometimes incomplete. | "availability unknown" fallback state exists specifically for this. |
| LLM latency or unavailability (Gemini free tier — rate limits, cold calls) could slow a turn past ~8 s or fail outright. | The LLM does only preference extraction — one bounded JSON call with a single short timeout, off the candidate / ranking / reason paths. A deterministic keyword+vocabulary parser produces the preference object with no network call, so recommendations still return. `mood_tags` precomputed on add (D6) and also optional. |
| The deployed app must not depend on a personal Claude subscription or paid Anthropic access. | LLM access is optional and behind a provider-agnostic interface (Gemini free tier initially). Every LLM-touched feature — preference extraction and `mood_tags` — has a deterministic path. Anthropic is never a required dependency. |
