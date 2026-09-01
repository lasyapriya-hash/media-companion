"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  getEntry,
  removeEntry,
  STATUS_LABELS,
  updateEntry,
  updateProgress,
  type LibraryEntryOut,
  type LibraryStatus,
} from "@/lib/api";
import { MediaDetail } from "@/components/media";

const STATUSES: LibraryStatus[] = ["want", "in_progress", "completed", "dropped"];

export default function ItemDetailPage() {
  const params = useParams<{ entryId: string }>();
  const entryId = params.entryId;
  const router = useRouter();

  const [entry, setEntry] = useState<LibraryEntryOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

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

  async function remove() {
    setRemoving(true);
    setRemoveError(null);
    try {
      await removeEntry(entryId);
      router.push("/");
    } catch (e) {
      setRemoveError(e instanceof Error ? e.message : String(e));
      setRemoving(false);
    }
  }

  if (error && !entry) return <div className="error">{error}</div>;
  if (!entry) return <p className="muted">Opening the page&hellip;</p>;

  const m = entry.media;

  return (
    <main>
      <Link href="/" className="backlink">
        &larr; Collection
      </Link>

      <MediaDetail media={m} favourite={favourite} yourRating={rating}>
          <section className="entry__section">
            <p className="kicker">Your notes</p>

            <div className="field">
              <label htmlFor="status" className="field-label">
                Status
              </label>
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
              <label className="check">
                <input
                  type="checkbox"
                  checked={favourite}
                  onChange={(e) => setFavourite(e.target.checked)}
                />
                Mark as a favourite
              </label>
            </div>

            <div className="field">
              <span className="field-label">
                Rating —{" "}
                {rating != null ? `${rating.toFixed(1)} / 10` : "not rated"}
              </span>
              <div className="row">
                <input
                  type="range"
                  min={1}
                  max={10}
                  step={0.5}
                  value={rating ?? 1}
                  onChange={(e) => setRating(Number(e.target.value))}
                  aria-label="Your rating"
                />
                <button
                  type="button"
                  className="ghost"
                  onClick={() => setRating(null)}
                >
                  Clear
                </button>
              </div>
            </div>

            <div className="field">
              <label htmlFor="review" className="field-label">
                Review &amp; notes
              </label>
              <textarea
                id="review"
                value={review}
                onChange={(e) => setReview(e.target.value)}
                placeholder="What you thought, what it reminded you of…"
                style={{ minHeight: "110px" }}
              />
            </div>

            <button onClick={saveDetails} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
            {error && <div className="error">{error}</div>}
            {notice && (
              <p className="notice" role="status">
                {notice}
              </p>
            )}
          </section>

          {m.type === "series" && (
            <section className="entry__section">
              <p className="kicker">Progress</p>
              <div className="row" style={{ alignItems: "flex-end" }}>
                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="seasonsDone" className="field-label">
                    Seasons completed
                  </label>
                  <input
                    id="seasonsDone"
                    type="number"
                    min={0}
                    value={seasonsDone}
                    onChange={(e) => setSeasonsDone(Number(e.target.value))}
                    style={{ width: "6rem" }}
                  />
                </div>
                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="curSeason" className="field-label">
                    Current season
                  </label>
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
                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="curEpisode" className="field-label">
                    Current episode
                  </label>
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
              <button
                onClick={saveProgress}
                disabled={saving}
                style={{ marginTop: "1rem" }}
              >
                {saving ? "Saving…" : "Save progress"}
              </button>
            </section>
          )}

          <section className="entry__section">
            <p className="kicker">Remove</p>
            {!confirmingRemove ? (
              <button
                type="button"
                className="danger"
                onClick={() => {
                  setConfirmingRemove(true);
                  setRemoveError(null);
                }}
              >
                Remove from collection
              </button>
            ) : (
              <div className="confirm-danger">
                <p className="confirm-danger__q">
                  Remove &ldquo;{m.title}&rdquo; from your collection?
                </p>
                <p
                  className="muted"
                  style={{ margin: 0, fontSize: "0.9rem" }}
                >
                  Your status, rating, review, and favourite flag
                  {m.type === "series" ? ", plus series progress," : ""} for
                  this entry will be deleted. The title itself stays
                  searchable and can still be recommended.
                </p>
                <div className="confirm-danger__actions">
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => setConfirmingRemove(false)}
                    disabled={removing}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="danger"
                    onClick={remove}
                    disabled={removing}
                  >
                    {removing ? "Removing…" : "Remove"}
                  </button>
                </div>
                {removeError && (
                  <div className="error">{removeError}</div>
                )}
              </div>
            )}
          </section>
      </MediaDetail>
    </main>
  );
}
