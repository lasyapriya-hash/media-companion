"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  getEntry,
  STATUS_LABELS,
  updateEntry,
  updateProgress,
  type LibraryEntryOut,
  type LibraryStatus,
} from "@/lib/api";

const STATUSES: LibraryStatus[] = ["want", "in_progress", "completed", "dropped"];

export default function ItemDetailPage() {
  const params = useParams<{ entryId: string }>();
  const entryId = params.entryId;

  const [entry, setEntry] = useState<LibraryEntryOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // editable state
  const [status, setStatus] = useState<LibraryStatus>("want");
  const [favourite, setFavourite] = useState(false);
  const [rating, setRating] = useState<number | null>(null);
  const [review, setReview] = useState("");
  const [seasonsDone, setSeasonsDone] = useState(0);
  const [curSeason, setCurSeason] = useState<number | "">("");
  const [curEpisode, setCurEpisode] = useState<number | "">("");

  function hydrate(e: LibraryEntryOut) {
    setEntry(e);
    setStatus(e.status);
    setFavourite(e.favourite);
    setRating(e.rating ?? null);
    setReview(e.review ?? "");
    setSeasonsDone(e.progress?.seasons_completed ?? 0);
    setCurSeason(e.progress?.current_season ?? "");
    setCurEpisode(e.progress?.current_episode ?? "");
  }

  useEffect(() => {
    getEntry(entryId)
      .then(hydrate)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e)),
      );
  }, [entryId]);

  async function saveDetails() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateEntry(entryId, {
        status,
        favourite,
        rating,
        review: review.trim() === "" ? null : review,
      });
      hydrate(updated);
      setNotice("Saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function saveProgress() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateProgress(entryId, {
        seasons_completed: seasonsDone,
        current_season: curSeason === "" ? null : Number(curSeason),
        current_episode: curEpisode === "" ? null : Number(curEpisode),
      });
      hydrate(updated);
      setNotice("Progress saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (error && !entry) return <div className="error-box">{error}</div>;
  if (!entry) return <p className="muted">Loading&hellip;</p>;

  const m = entry.media;

  return (
    <main>
      <p>
        <Link href="/">&larr; Library</Link>
      </p>

      <div className="detail-layout">
        <div>
          {m.artwork_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="poster" src={m.artwork_url} alt={m.title} />
          ) : (
            <div
              className="poster"
              style={{ aspectRatio: "2 / 3", background: "var(--panel-2)" }}
            />
          )}
        </div>

        <div>
          <h1 style={{ marginTop: 0 }}>
            {m.title} {favourite ? "★" : ""}
          </h1>
          <div className="chips" style={{ marginBottom: "0.75rem" }}>
            <span className="badge">{m.type}</span>
            {m.year && <span className="badge">{m.year}</span>}
            {m.language && <span className="badge">{m.language}</span>}
            {m.length_bucket && <span className="badge">{m.length_bucket}</span>}
            {m.external_rating != null && (
              <span className="badge">source ★ {m.external_rating}</span>
            )}
          </div>

          {m.author && <p className="muted">by {m.author}</p>}
          {m.type === "movie" && m.runtime_minutes && (
            <p className="muted">{m.runtime_minutes} min</p>
          )}
          {m.type === "series" && (
            <p className="muted">
              {m.seasons ?? "?"} seasons · {m.episodes ?? "?"} episodes
              {m.episode_runtime_minutes
                ? ` · ~${m.episode_runtime_minutes} min/ep`
                : ""}
            </p>
          )}
          {m.type === "book" && m.page_count && (
            <p className="muted">{m.page_count} pages</p>
          )}

          {m.genres.length > 0 && (
            <div className="chips" style={{ margin: "0.5rem 0" }}>
              {m.genres.map((g) => (
                <span key={g} className="badge">
                  {g}
                </span>
              ))}
            </div>
          )}

          {m.description && <p>{m.description}</p>}

          <p className="muted" style={{ fontSize: "0.85rem" }}>
            Mood tags:{" "}
            {m.mood_tags.length > 0
              ? m.mood_tags.join(", ")
              : "not yet classified"}
          </p>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {notice && (
        <p className="status-ok" role="status">
          {notice}
        </p>
      )}

      <section className="panel" style={{ marginTop: "1.5rem" }}>
        <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>Your tracking</h2>

        <div className="field">
          <label htmlFor="status">Status</label>
          <select
            id="status"
            value={status}
            onChange={(e) => setStatus(e.target.value as LibraryStatus)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label>
            <input
              type="checkbox"
              checked={favourite}
              onChange={(e) => setFavourite(e.target.checked)}
            />{" "}
            Favourite
          </label>
        </div>

        <div className="field">
          <label htmlFor="rating">
            Rating: {rating != null ? `${rating.toFixed(1)} / 10` : "none"}
          </label>
          <div className="row">
            <input
              id="rating"
              type="range"
              min={1}
              max={10}
              step={0.5}
              value={rating ?? 1}
              onChange={(e) => setRating(Number(e.target.value))}
            />
            <button
              type="button"
              className="secondary"
              onClick={() => setRating(null)}
            >
              Clear
            </button>
          </div>
        </div>

        <div className="field">
          <label htmlFor="review">Review / notes</label>
          <textarea
            id="review"
            value={review}
            onChange={(e) => setReview(e.target.value)}
          />
        </div>

        <button onClick={saveDetails} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </section>

      {m.type === "series" && (
        <section className="panel" style={{ marginTop: "1rem" }}>
          <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>Series progress</h2>
          <div className="row">
            <div className="field">
              <label htmlFor="seasonsDone">Seasons completed</label>
              <input
                id="seasonsDone"
                type="number"
                min={0}
                value={seasonsDone}
                onChange={(e) => setSeasonsDone(Number(e.target.value))}
                style={{ width: "6rem" }}
              />
            </div>
            <div className="field">
              <label htmlFor="curSeason">Current season</label>
              <input
                id="curSeason"
                type="number"
                min={0}
                value={curSeason}
                onChange={(e) =>
                  setCurSeason(
                    e.target.value === "" ? "" : Number(e.target.value),
                  )
                }
                style={{ width: "6rem" }}
              />
            </div>
            <div className="field">
              <label htmlFor="curEpisode">Current episode</label>
              <input
                id="curEpisode"
                type="number"
                min={0}
                value={curEpisode}
                onChange={(e) =>
                  setCurEpisode(
                    e.target.value === "" ? "" : Number(e.target.value),
                  )
                }
                style={{ width: "6rem" }}
              />
            </div>
          </div>
          <button onClick={saveProgress} disabled={saving}>
            {saving ? "Saving…" : "Save progress"}
          </button>
        </section>
      )}
    </main>
  );
}
