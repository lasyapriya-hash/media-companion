# Personal Media Companion — Specification

| | |
|---|---|
| **Version** | 2.0 — establishes Media Companion as a **multi-user** product: every account has its own library, ratings/reviews/favourites, series progress, derived taste profile, and recommendation sessions, all private to that account; media metadata stays shared/global across accounts (§2, §6, §11, §13). Supersedes v1.x, which specified a single-user product with authentication treated as an add-on. See plan.md for implementation/rollout history. |
| **Date** | 2026-09-10 |
| **Owner** | lasyapriya@iisc.ac.in |
| **Status** | Living document — describes the intended product and architecture, not implementation status or a changelog |

---

## 1. Overview

Build a **multi-user** personal media companion that unifies **movies, TV
series, and books** in one library per account and lets each user describe
what they feel like watching or reading in **natural language** — mood,
situation, and constraints — instead of selecting filters. Every account's
library, ratings, taste profile, and recommendations are private to that
account; the underlying media catalog is shared, global reference data
reused across all accounts (§2, §6).

The system:

1. Infers a structured set of preferences from the free-text request.
2. Asks **at most one** clarifying follow-up, and only if the request is
   genuinely too sparse to act on.
3. Returns a **ranked** list of recommendations, each with a one-sentence,
   request-specific reason.

Recommendations are explicitly **not** a "highest-rated first" list.

---

## 2. Target User & Problem

Media Companion is a **multi-user** application. Anyone can register their
own account and gets, from that point on, an independent and private
library, independent ratings/reviews/favourites/progress, an independently
computed taste profile, and independent recommendation sessions (§6). One
account's data — what it has added, rated, reviewed, marked as favourite, or
asked for recommendations about — is never visible to, or affected by, any
other account (§6.1, §11, §13).

The underlying media catalog — titles, genres, synopses, provider ratings,
availability (`media_item`, §6.1) — is **shared, global reference data**: it
is fetched once from the external providers (TMDb, Open Library / Google
Books), cached, and reused across every account, never duplicated per user.
Two different accounts can each hold the same title in their own library,
with completely independent status, rating, review, favourite, and progress,
both referencing the same shared metadata record.

*Historical note:* the project began as a personal, single-user tool for its
original owner, with no account system at all. It has since been
generalized into a multi-user product; the single-user framing no longer
describes the intended system (plan.md has that development history).

The problem being solved, for any given account: media tracking today is
split across separate apps for movies/series and books, and recommendations
tend to be static filters or "highest rated" lists rather than driven by
*"what do I feel like right now."*

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

- Add any searched item (movie, series, or book) to **the authenticated
  account's own library**. Every action below (status, favourite, rating,
  review, progress) applies to that account's own copy of the item only —
  never to any other account's (§6.1, §11).
- **Status:** `want` · `in_progress` · `completed` · `dropped`.
- **Favourite** flag.
- **Personal rating:** 1–10, half-steps allowed (1.0, 1.5, … 10.0). Optional.
- **Review / notes:** free text. Optional.
- **Progress:** seasons / episodes for series only. Movies have no progress;
  books have status only (no page or percentage tracking in v0).
  - **Season-aware.** When per-season episode counts are known for a series
    (§6.1 `season_episode_counts`), the current season is chosen from the
    series' actual seasons and the current episode is constrained to that
    season's real episode count — not a freely-typed pair of numbers.
    Season 0 ("Specials") is excluded from season selection and validation.
  - **Automatic rollover.** Advancing from the final episode of a season
    moves to episode 1 of the next season. Advancing from the final episode
    of the *final* season offers marking the series completed instead of
    inventing a season that doesn't exist.
  - **`seasons_completed` is derived, not independently editable.** Whenever
    `current_season` is supplied, the backend recomputes
    `seasons_completed = max(current_season - 1, 0)` itself and ignores any
    client-supplied value for it in that request — the two fields can never
    disagree. A caller that updates `seasons_completed` alone (without
    touching `current_season`) keeps the direct legacy behavior.
  - **Backend-validated independently of the UI.** An episode number outside
    the selected season's known range, or a season number that doesn't exist
    for that series, is rejected server-side — the frontend's own
    constraints are a convenience, not the enforcement.
  - **Legacy entries** added before per-season data was cached
    (`season_episode_counts` absent) skip this bound-checking rather than
    fabricating an episode count that isn't actually known.
  - **Completed series hide the progress controls** in the UI; the saved
    progress is not deleted, and switching status back to `in_progress`
    restores it exactly as it was.

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

- Every recommendation request is made by an authenticated account and
  evaluated entirely in that account's own context: the exclusion of
  already-completed/dropped titles (§9) and the personalization context
  handed to Gemini (§6.3, §9.0) both come from that account's own library
  and taste profile only, never another account's.
- User describes mood / situation / constraints in free text.
- **Gemini is the primary recommendation intelligence**, not just an
  extractor. One bounded call both (a) extracts a **structured preference
  object** (Section 7) — the *objective* constraints the user stated — and
  (b) directly judges which real titles semantically fit the request (genre,
  mood, tone, vibe, theme), using its own knowledge rather than a fixed tag
  vocabulary, returning a bounded list of suggested titles with its own
  one-sentence reason for each. See Section 9.0 for exactly what happens to
  those suggestions, and Section 9.1/9.2 for the deterministic fallback used
  when Gemini is unavailable or nothing it suggests survives validation.
- **Clarification rule:** if the extracted preferences are too sparse for a
  confident recommendation **and Gemini did not already return usable
  suggestions**, the agent asks **exactly one** follow-up question, then
  proceeds regardless of the answer. Hard cap of one clarifying turn — no
  open-ended back-and-forth. Precise rule in Section 8.3.
- **Session state** (the request, any clarification Q&A, the extracted
  preference object) lives only for the duration of that recommendation
  session. No cross-session conversation history in v0.
- On the primary (Gemini) path, ranking is **Gemini's own suggestion order**
  — the deterministic weighted score (Section 9.1/9.2) is not computed for
  these results. On the deterministic fallback path, ranking combines extracted
  preferences with the taste profile (Section 6.3) via the weighted score for
  movies/series, or genre / mood-tag overlap for books, exactly as before.
- Each recommendation carries a **one-sentence reason**. On the primary path
  this is Gemini's own reason for that title, used as-is. On the fallback
  path it is assembled deterministically from the matched signals (Section
  9.4), as before.
- Recommendations must **not** simply be the highest-rated items (Section 9.3)
  — this remains true on both paths (Gemini is instructed not to pad its list
  with a weak match, and the fallback's novelty term is not rating-driven).

### 5.4 Availability

- **Movies / series:** streaming/platform availability via TMDb watch
  providers, region = India. If no provider data exists, show
  **"availability unknown"** — never an error or a blank.
- **Books:** show a purchase/access link if the book API returns one;
  otherwise omit the field cleanly (no broken links, no placeholder text).

---

## 6. Data Model

Persistence is **Postgres**. Ownership is structured around the account
(`user`, §6.1): a `library_entry` — and everything that hangs off it
(`series_progress`) — belongs to exactly one account; `taste_profile` and
`recommendation_session` likewise each belong to exactly one account.
`media_item` (the cached provider metadata) is the one deliberate exception:
it is shared/global, never owned by any account, and is referenced by
however many different accounts' `library_entry` rows point at it — never
duplicated per user.

```
user ─┬─▶ library_entry ─▶ series_progress
      ├─▶ taste_profile
      └─▶ recommendation_session

media_item ◀── library_entry   (shared/global; many accounts may reference the same row)
```

### 6.1 Entities

#### `user` — an account

| Field | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `email` | varchar(320) | normalized (stripped + lowercased) before storage; unique |
| `hashed_password` | text | bcrypt |
| `created_at` | timestamptz | |

**Constraints:** `unique (email)`. Every `library_entry`, `taste_profile`,
and `recommendation_session` row references exactly one `user` row
(`ON DELETE CASCADE` — deleting an account deletes all of that account's
data: its library entries, series progress, taste profile, and
recommendation sessions).

#### `media_item` — cached external metadata (shared/global, never user-owned)

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
| `season_episode_counts` | jsonb, null | series — `[{season_number, episode_count, name}]` from the provider; includes season 0 ("Specials") for completeness, but season 0 is excluded from progress selection/validation (Section 5.1). `null` for entries added before this field existed — treated as "unknown," never fabricated |
| `author` | text, null | books |
| `page_count` | int, null | books |
| `mood_tags` | text[] | derived tone/mood tags (see 6.4); used for matching |
| `raw_metadata` | jsonb | full provider payload, for debugging and later fields |
| `fetched_at` | timestamptz | cache freshness |

**Constraints:** `unique (source, source_id)`.

#### `library_entry` — one account's relationship to an item (user-owned)

| Field | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `user_id` | uuid, FK → `user.id`, not null | the owning account; every entry belongs to exactly one account; `ON DELETE CASCADE` |
| `media_item_id` | uuid, FK → `media_item.id` | |
| `status` | enum `want` \| `in_progress` \| `completed` \| `dropped` | required |
| `favourite` | bool, default false | |
| `rating` | numeric, null | 1.0–10.0, constrained to 0.5 steps |
| `review` | text, null | |
| `added_at` | timestamptz | |
| `updated_at` | timestamptz | |

**Constraints:** `unique (user_id, media_item_id)` — a title can appear at
most once in a given account's library, but the same title can independently
appear in any number of *other* accounts' libraries, each referencing the
same shared `media_item` row (never a duplicate).
>
> **Ownership enforcement:** every `/library*` endpoint requires a valid,
> authenticated account (§13) and every service operation — list, get,
> update, update-progress, remove — is scoped to the calling account through
> a single ownership check. Requesting or mutating another account's entry
> returns the same "not found" response as a nonexistent id; the API never
> confirms that another account's entry exists, so ownership can't be probed
> by ID-guessing. `taste_profile` and `recommendation_session` are scoped
> the same way — see their entity sections below and §13.

#### `series_progress` — series only

| Field | Type | Notes |
|---|---|---|
| `library_entry_id` | uuid, PK, FK → `library_entry.id` | |
| `seasons_completed` | int, default 0 | **server-derived** when `current_season` is set on the same request (`= max(current_season - 1, 0)`); the client's own value is ignored in that case — see Section 5.1 |
| `current_season` | int, null | validated against `media_item.season_episode_counts` when known (Section 5.1); season 0 is never a valid value here |
| `current_episode` | int, null | validated against the selected season's real episode count when known |
| `updated_at` | timestamptz | |

Rows exist only for entries whose `media_item.type = 'series'`. No `user_id`
of its own — ownership is inherited automatically through its 1:1
`library_entry_id` FK (`ON DELETE CASCADE`), so `library_entry`'s ownership
checks already cover it (ability to read/write a series' progress requires
owning its `library_entry`, same as any other field on it).

#### `recommendation_session` — optional, non-durable

The conversation is session-scoped (Section 8.4). A backend that cannot hold
state in memory MAY persist sessions here for statelessness and debugging, but
rows are **not** surfaced as user-visible history and MAY be pruned freely.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid, PK | session id returned to the client |
| `user_id` | uuid, FK → `user.id`, not null | the owning account; every session is created by, and belongs to, exactly one authenticated account |
| `original_request` | text | |
| `preference_object` | jsonb | latest extracted preferences (Section 7) |
| `clarification_question` | text, null | the single question, if one was asked |
| `clarification_answer` | text, null | user's reply, if any |
| `clarification_used` | bool, default false | **invariant: once true, no further question may be asked** |
| `results` | jsonb, null | ranked recommendation payload |
| `state` | enum (Section 8.1) | |
| `created_at` | timestamptz | |

**Ownership:** `POST /recommendations` sets `user_id` to the caller; every
later operation on a session (e.g. `POST /recommendations/{id}/answer`)
checks it the same way `library_entry` ownership is checked — a session that
exists but belongs to a different account is indistinguishable from one that
doesn't exist, and the session UUID's own unguessability is deliberately
*not* relied on as the only protection.

Being owned data does not make this table user-visible history: it is
explicitly debug/prunable data (this section, and §8.4) and rows MAY be
pruned freely regardless of age. Ownership just determines *who*, while a
row exists, is allowed to read or answer it.

### 6.2 Enumerations

- `media_type`: `movie`, `series`, `book`
- `library_status`: `want`, `in_progress`, `completed`, `dropped`
- `source`: `tmdb`, `open_library`, `google_books`
- `length_bucket`: `short`, `medium`, `long` (mapping in 6.4)
- `intensity`: `low`, `medium`, `high`
- `session_state`: `extracting`, `needs_clarification`, `awaiting_answer`,
  `ranking`, `results`, `error`

### 6.3 Taste Profile (derived, not a trained model)

Recomputed on every rating change and every status change, scoped to the
account that made the change. **One row per account** —
`taste_profile.user_id` (FK → `user.id`, `ON DELETE CASCADE`) is the primary
key itself, so "one profile per account" is a structural guarantee, not a
convention: a second row for the same account is a primary-key violation.
`taste_profile.recompute()`/`get_or_compute()` both require `user_id` and
only ever read that account's own `library_entry` rows — one account's
library changes never affect another's profile, and a profile is never
computed from more than one account's data combined.

| Signal | Definition |
|---|---|
| `favourite_genres` | genres ranked by (count of `completed` + `favourite`) then by average rating |
| `favourite_languages` | languages ranked the same way |
| `avg_rating_by_genre` | map: genre → mean personal rating over rated items in that genre |
| `avg_rating_by_language` | map: language → mean personal rating |
| `completion_rate` | `completed` ÷ (`completed` + `dropped`), overall and per genre |
| `drop_patterns` | genres/languages with completion_rate below a low threshold |
| `computed_at` | timestamptz |

Used as a scoring input for **movie/series** recommendations (the
deterministic fallback, Section 9.1) and as the personalization context
summarized into the **Gemini-primary path's** prompt (`taste_context`,
Section 9.0) — always built from the calling account's own profile only,
never another account's. For **books** in v0 it is used only as a light
tiebreaker, if at all.

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
  "rating":        { "gte": num, "gt": num, "lte": num, "lt": num } | null,
                               // explicit numeric bound on external_rating (0-10);
                               // inclusive/exclusive carried per-field ("above 7.5" -> gt,
                               // "at least 7.5" -> gte); a HARD filter, same as avoid
  "avoid":         string[],   // genres / themes / content to hard-exclude
  "explicit_fields": string[]  // which of the above the user stated outright
                               // (vs. inferred) — drives the sparsity check
}
```

`avoid` and an explicit `rating` bound are always **hard filters**, never a
soft signal. So are an explicit `language` and an explicit `media_type` or
`release_period` (Section 9.1/9.0) — an explicit language that fails to
resolve to a known code is treated as a hard filter nothing can satisfy, never
silently widened into an unrestricted query.

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
- Gemini is the **primary** source of both the preference object and the
  candidate title list (Section 5.3, Section 9.0) — this is a deliberate
  architecture choice, not a gap. What deterministic backend code guarantees
  instead: every Gemini-suggested title is resolved against a real metadata
  provider before it can be shown (Section 9.0.1), every *objective* fact
  about it (language, media type, rating, release period, whether it's
  already in the excluded collection) is independently verified against that
  provider's data — Gemini is never trusted for these (Section 9.0.2) — and
  whenever Gemini is unavailable, returns nothing usable, or every suggestion
  fails resolution/validation, candidate generation, scoring, and ranking fall
  back to the fully deterministic pipeline of Section 9.1/9.2, driven by the
  preference object and the taste profile with no LLM involvement at all. The
  single clarifying question (Section 8.3) is always template-produced, never
  by the LLM, on either path.

### 8.3 Sparsity rule (precise)

Let the **richness set** be the populated fields among:
`media_type, mood, tone, genres, length, intensity, language, release_period`.
(`avoid` does **not** count toward richness.)

Preferences are **sufficient** — proceed straight to `ranking` — if **any** of:

1. `genres` is non-empty; **or**
2. `mood` is non-empty **and** at least one of
   `{tone, media_type, length, language}` is populated; **or**
3. three or more fields in the richness set are populated; **or**
4. Gemini's own primary-path call (Section 9.0) already returned at least one
   usable title suggestion — Gemini being confident enough to suggest
   something is itself treated as sufficient, regardless of how sparse the
   *structured* preference object looks, since the old richness heuristic was
   designed for a tag-matching engine that no longer decides relevance on
   this path.

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
  addressable by `session.id` for the duration of that interaction. It
  belongs to the authenticated account that created it (§6.1); no other
  account can read or answer it.
- Nothing about the conversation needs to persist once results are delivered.
  Any persisted `recommendation_session` row is debug data and may be pruned.
- There is no "resume previous recommendation chat" feature in v0.

---

## 9. Recommendation Scoring

There are now two paths to a result list: the **primary** (Gemini-selected)
path, and the **deterministic fallback**. Both apply the same hard exclusion
of anything with `library_entry.status = completed` or `dropped`; on the
fallback path `avoid` is also a keyword-matched hard exclusion (Section 9.1),
while on the primary path `avoid` is instead given to Gemini as an instruction
not to suggest such a title in the first place (Section 9.0.2) — reusing the
fallback's keyword filter there would recreate the same "provider tag decides
semantic relevance" problem this architecture exists to avoid for genre.

### 9.0 Primary path: Gemini-selected candidates

Gemini (Section 5.3) judges semantic fit itself — genre, mood, tone, theme,
vibe — using its own knowledge, and returns a bounded list (currently up to
12) of `{title, media_type, year, reason}` suggestions in the order it judges
them to fit. That order is preserved as the final ranking; the deterministic
weighted score of Section 9.1/9.2 is **not** computed for candidates on this
path. Gemini's own `reason` string is used as the displayed reason, as-is
(Section 9.4). Gemini is never asked for, and never trusted for, a rating,
runtime, streaming availability, or provider ID — those are facts, supplied
only by resolving against the real metadata providers below.

Alongside the request text, the call includes a short **taste-context**
summary (favourite genres/languages, drop patterns — Section 6.3) generated
from the calling account's own taste profile, explicitly framed as
background only — it never overrides or substitutes for anything the request
states outright. This is always the calling account's own profile, never
another account's (Section 6.3).

#### 9.0.1 Title resolution (hallucination guard)

Each suggested title is looked up by name (+ approximate year, if Gemini gave
one) against a real provider — TMDb for movies/series, Open Library then
Google Books for books — using the provider's title-search endpoint, not a
genre/filter query. A title/year confidence check (plain string similarity,
not a semantic classifier) must clear a threshold for the match to be
accepted; a suggestion with no confident match is **discarded** — never shown,
never assumed real. This is the only defense against a fabricated or
misremembered title: it must round-trip through a real provider and match
with confidence, or it doesn't appear.

#### 9.0.2 Objective validation

Once resolved, a candidate must still pass every constraint below —
Gemini's semantic judgment is authoritative for *fit*, never for these facts:

- an explicit **language** (Section 7) matches the resolved item's actual
  language;
- an explicit **media type** matches the resolved item's actual type;
- an explicit **rating** bound (Section 7) is met by the resolved item's real
  `external_rating`;
- an explicit **release period** is met by the resolved item's real year;
- the resolved item is not already excluded by the calling account's own
  collection status (`completed`/`dropped`);
- the resolved item clears the same minimum-quality floor as the fallback
  path (Section 9.3).

**Deliberately not checked here: genre.** Provider genre tags were found to be
too coarse/incomplete to arbitrate a semantic request (e.g. a real, correctly
Telugu-language romantic drama may carry no "Romance" tag at all) — the
fallback path's genre matching (Section 9.1) is not reused on this path for
that reason. `hits_avoid`'s keyword matching (Section 9.1) is likewise not
reused here — `avoid` terms are instead given to Gemini as an instruction, per
above. If nothing Gemini suggested survives resolution and this validation,
the request falls through to the deterministic fallback below — the user is
never shown an empty result merely because the primary path came up short.

### 9.1 Deterministic fallback — movies / series

Used when Gemini is unavailable, times out, returns malformed output, or
nothing it suggested survives Section 9.0.1/9.0.2. Candidates come from
external-API queries built from the preference object (genre filters,
language, release window, type); the candidate pool excludes
`completed`/`dropped` items and hard-excludes anything matching `avoid`
(keyword match against title/description/genre/mood-tags), an explicit
`rating` bound, an explicit `language`, or an explicit `media_type` — all
hard filters, not merely down-ranked. Items already in the library with
status `want` are eligible.

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
- **novelty_term** — a blend of two things, both 0–1: obscurity (lower
  provider popularity → higher novelty, so the list cannot collapse to "most
  popular") and a quality prior from `external_rating`. The rating half is
  monotonic — a higher rating can only raise this term, never lower it. (An
  earlier version of this term let a low rating masquerade as "novelty" and
  actively outranked well-reviewed candidates; that inversion is fixed —
  rating is a quality signal here, never a punishment.) With no preference or
  taste signal at all (a fully open-ended request), this term is quality
  alone, so an unconstrained list still favours a well-reviewed pick over a
  merely-obscure one.
- **penalty** — additive deductions for soft-avoid theme hits and for genres
  in the user's `drop_patterns`.

Suggested starting weights (tune during build): `w1 = 0.50`, `w2 = 0.35`,
`w3 = 0.15`. `external_rating` never enters the sort key as a primary
criterion — only as the minimum-quality floor (drops obvious junk) and, at
low weight and always in the quality-favouring direction, inside
`novelty_term` above.

### 9.2 Deterministic fallback — books (v0, lighter)

```
score = genre_overlap + mood_tag_overlap
```

Both terms 0–1. Taste profile enters only as a tiebreaker
(`avg_rating_by_genre` where data exists). Same hard-exclusions and same
`avoid` filter as 9.1.

### 9.3 "Not highest-rated" guarantee

- **Fallback path:** the ranking sort key is `score`, never `external_rating`
  or `rating` directly; `external_rating` only ever pulls a candidate up
  within the low-weight `novelty_term`, never used as the primary sort key.
- **Primary path:** ranking is Gemini's own order (Section 9.0), which is
  instructed not to pad the list with a weak or unrelated match — Gemini may
  legitimately rank a lower-rated title first when it's a better semantic
  fit, which is the point.
- `external_rating` is capped to a low-weight quality floor on both paths
  (Section 9.0.2, Section 9.1).
- **Acceptance test (fallback path):** issue a request whose mood/tone
  deliberately conflicts with the highest-rated candidate; assert that
  candidate is not ranked #1.

### 9.4 Output

- Top **N** results (N in Section 15; default 8).
- Each result: the `media_item` display fields, the availability block
  (Section 5.4), the `score`, and a **one-sentence reason**. On the
  **fallback** path this is assembled deterministically from the structured
  match explanation — a template over which sub-signals matched (genres,
  mood/tone, length, language, period) plus one taste-profile fact. On the
  **primary** path this is Gemini's own reason for that title, used verbatim
  — not a template, and not re-derived from provider tags. Reasons must be
  request-specific, not generic; on the fallback path the template names the
  request's own matched fields (no LLM call), and on the primary path Gemini
  is explicitly prompted to give a fit-specific sentence rather than a
  generic one — and never a rating/runtime/availability claim, since those
  aren't facts Gemini is trusted for (Section 9.0.2).

---

## 10. External APIs & Data Sources

| Source | Use |
|---|---|
| **TMDb** | movie/series search/discover, metadata, watch providers (region IN); also resolves Gemini-suggested movie/series titles by name (Section 9.0.1) |
| **Open Library** *(primary)* or **Google Books** *(fallback / primary — 15)* | book search and metadata; also resolves Gemini-suggested book titles by name (Section 9.0.1) |
| **LLM provider** — Google **Gemini** (currently `gemini-3.5-flash-lite`, pinned rather than tracking `-latest`), behind a provider-agnostic interface so it can be swapped | The **primary** recommendation intelligence (Section 5.3, 9.0): one bounded call per turn both extracts the structured preference object (Section 7) and judges semantic fit, returning a bounded candidate title list with reasons. **Never trusted for objective facts** (rating, runtime, availability, existence) — those are always verified against the data-API providers (Section 9.0.2). The optional `mood_tags` classification (Section 6.4) is a separate, second bounded call type. Always behind a deterministic fallback (Section 9.1/9.2) — the app is fully usable with **no LLM provider and no Anthropic access**, just with tag-matched rather than semantic candidates. |

Keeping every *objective* fact verified against the data APIs — never taken on
Gemini's word — bounds both cost/latency and the risk of a hallucinated or
factually wrong result reaching the user; keeping a fully deterministic
fallback means the deployed app never depends on paid or personal-subscription
LLM access, even though Gemini is now the primary path when available.

---

## 11. Functional Requirements

- **FR1** — A person can register an account and authenticate (log in) to use
  the product; every requirement below operates in the context of that
  authenticated account.
- **FR2** — An authenticated user can search and add any movie/series/book to
  their own library.
- **FR3** — An authenticated user can set/change status, rating, review,
  favourite, and (series only) season/episode progress on any item in their
  own library.
- **FR4** — An authenticated user can submit a free-text recommendation
  request.
- **FR5** — System extracts a structured preference object from that request.
- **FR6** — System asks at most one clarifying question when preferences are
  sparse (rule 8.3), then always produces a recommendation list.
- **FR7** — Each recommendation includes a one-sentence, request-specific
  reason.
- **FR8** — System shows availability info, or a clean "unknown" state, for
  each recommended and viewed item.
- **FR9** — All external API keys are stored and used server-side only, never
  exposed to the frontend/browser.
- **FR10** — Each user's taste profile is recomputed on every rating change
  and every status change to that user's own library, and is derived only
  from that user's own data.
- **FR11** — One user's library, ratings, reviews, series progress, taste
  profile, and recommendation sessions are never visible to, retrievable by,
  or modifiable by another user — including by directly addressing another
  account's resource IDs while authenticated as a different account, which
  must behave identically to that resource not existing (§6.1).

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
| LLM | Provider-agnostic interface; Google Gemini (`gemini-3.5-flash-lite`) is the **primary** recommendation intelligence (Section 5.3, 9.0), not just extraction. The optional `mood_tags` call (Section 6.4) is a separate, second bounded call type. Optional — a fully deterministic fallback keeps the engine working with no LLM access; no Anthropic / personal-subscription dependency |
| Auth | Account registration and login by email + password; the password is bcrypt-hashed server-side and never stored or returned in plaintext (`User` model: UUID id, unique normalized email, hashed password). A successful login issues a bearer token (JWT, HS256, default 7-day expiry) that authenticates every subsequent request. A single dependency verifies the token and loads the calling account on every protected route; a missing, malformed, expired, or otherwise invalid token is rejected (401) before any handler body runs. Every library, taste-profile, and recommendation endpoint requires this and is scoped to the calling account (Section 6.1, Section 11) — one account can never see or modify another's resources through the API. Search and media-details endpoints remain public and unauthenticated — they're stateless, provider-facing lookups with no per-account data. |
| Deployment | backend + Postgres on Render; frontend on Vercel (Section 15 D2 resolved to split) |

---

## 14. Deployment Requirements

- A working **public URL**; no local-only functionality.
- Environment variables for **all** API keys (TMDb, book API, the LLM
  provider — `GEMINI_API_KEY` — and the auth signing configuration —
  `JWT_SECRET_KEY` / `JWT_ALGORITHM` / `JWT_EXPIRES_MINUTES`). Never
  committed to the repo, never shipped to the client bundle. The backend
  must start and serve recommendations even when the LLM provider key is
  absent.

**Current live deployment:**

| | |
|---|---|
| Frontend | https://media-companion-silk.vercel.app |
| Backend | https://media-companion-api.onrender.com |
| Database | Render Postgres |

The backend calls Gemini, TMDb, and Open Library / Google Books as described
in Section 10.

---

## 15. Open Decisions (resolve during implementation)

| # | Decision | Default if undecided |
|---|---|---|
| D1 | Book API: Open Library vs Google Books as primary | Open Library primary, Google Books fallback |
| D2 | Deploy topology: split (Render/Railway + Vercel) vs combined | **Resolved: split** — Render (backend + Postgres) + Vercel (frontend), see Section 14 |
| D3 | `N` — number of recommendations returned | 8 |
| D4 | Scoring weight vector `w1/w2/w3` and sub-signal weights | 0.50 / 0.35 / 0.15 — **applies to the deterministic fallback only** (Section 9.1); the primary Gemini path is not weighted-scored at all (Section 9.0) |
| D5 | Rating input widget granularity (slider vs 10 half-star clicks) | slider, 0.5 steps |
| D6 | Whether `mood_tags` classification is precomputed on add vs lazily on first recommendation use | on add |
| D7 | LLM provider + model | **Resolved:** Google Gemini, `gemini-3.5-flash-lite` — pinned, not `-latest` (an earlier pinned model, `gemini-2.5-flash`, was retired for new API keys/tiers, and the "obvious" replacement Google suggested turned out to be a slower "thinking" model unsuitable for this bounded call; `gemini-3.5-flash-lite` has no reasoning-token overhead). Now used for the **primary recommendation call** (Section 9.0), not only extraction; deterministic fallback always present. |

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

**Multi-user / isolation:**

- [ ] A person can register a new account and log in.
- [ ] An unauthenticated request to any library, taste-profile, or
      recommendation endpoint is rejected.
- [ ] Two independent accounts (A and B) can each add the *same* title to
      their own library, with fully independent status/rating/review/
      progress, both referencing the same shared media metadata (no
      duplicate `media_item` row).
- [ ] Account A cannot read or modify account B's library entry, series
      progress, taste profile, or recommendation session — including by
      directly addressing account B's resource IDs while authenticated as
      account A.
- [ ] Account A's and account B's taste profiles differ correctly based only
      on each account's own library (e.g. differing favourite genres).
- [ ] Marking a title `completed`/`dropped` in account A's library excludes
      it from account A's future recommendations, but does **not** exclude
      it from account B's.

---

## 17. Explicitly Out of Scope (v0)

- Book page / percentage progress tracking.
- Full taste-profile scoring for book recommendations.
- Social features (sharing, following, messaging).
- Streaming or hosting media content.
- Open-ended (unbounded) conversational clarification.
- A trained / from-scratch ML recommendation model.
- Cross-session conversation history.

**No longer out of scope:** LLM-generated candidate lists and reason text —
Gemini is now the primary source of both (Section 9.0), with every objective
fact independently verified and every suggestion resolved against a real
provider before it can be shown (Section 9.0.1/9.0.2); the LLM still never
computes the deterministic `score` (Section 9.1) and never decides the
single clarifying question's wording. Multi-user accounts and per-account
data isolation are likewise no longer out of scope — they are core to the
product (§2, §6, §11, §13), not an optional extension.

---

## 18. Known Risks

| Risk | Mitigation |
|---|---|
| Multi-turn conversation state adds real complexity — session handling and the exact one-question rule need precise logic. The main implementation-complexity risk in v0. | State machine and sparsity rule are fully specified (Sections 8.1–8.3); `clarification_used` is a hard invariant; fallback path guarantees a result. |
| Book API coverage/quality varies more than TMDb's. | Lighter v0 scope for books deliberately absorbs this; primary/fallback API pair (D1). |
| TMDb watch-provider data is region-specific and sometimes incomplete. | "availability unknown" fallback state exists specifically for this. |
| LLM latency or unavailability (Gemini free tier — rate limits, cold calls) could slow a turn past ~8 s or fail outright. Gemini is now the *primary* recommendation source, not just extraction, so this risk is larger than originally scoped. | One bounded JSON call per turn, single short timeout. On any failure, malformed output, or an empty/all-discarded suggestion list, the engine falls through to the fully deterministic pipeline (Section 9.1/9.2) with no network call — recommendations still return either way. `mood_tags` precomputed on add (D6) and also optional. |
| A Gemini-suggested title could be hallucinated or misremembered. | Every suggestion must resolve against a real provider by title/year with a confidence check before it can be shown (Section 9.0.1); an unconfident or unresolved suggestion is discarded, never displayed. |
| Provider genre tags are too coarse/incomplete to arbitrate a semantic request (e.g. a correctly Telugu-language romantic drama with no "Romance" tag). | Genre is deliberately not hard-validated on the primary path (Section 9.0.2) — Gemini's own semantic judgment is authoritative for fit; only objective, provider-verifiable facts (language, media type, rating, release period, collection status) are checked. |
| The deployed app must not depend on a personal Claude subscription or paid Anthropic access. | LLM access is optional and behind a provider-agnostic interface (Gemini free tier). Every LLM-touched feature — the primary recommendation call and `mood_tags` — has a deterministic path. Anthropic is never a required dependency. |
