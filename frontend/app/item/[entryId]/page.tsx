"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  getEntry,
  getMediaDetails,
  removeEntry,
  STATUS_LABELS,
  updateEntry,
  updateProgress,
  type LibraryEntryOut,
  type LibraryStatus,
  type SeasonInfo,
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
  const [curSeason, setCurSeason] = useState<number | "">("");
  const [curEpisode, setCurEpisode] = useState<number | "">("");
  // Per-season episode counts, real TMDb data — never hard-coded (spec §16).
  // A collected series already carries this on `media` once re-added/enriched
  // after this feature shipped; older entries fall back to a live fetch below.
  const [seasonData, setSeasonData] = useState<SeasonInfo[] | null>(null);
  const [advancing, setAdvancing] = useState(false);

  function hydrate(e: LibraryEntryOut) {
    setEntry(e);
    setStatus(e.status);
    setFavourite(e.favourite);
    setRating(e.rating ?? null);
    setReview(e.review ?? "");
    setCurSeason(e.progress?.current_season ?? 1);
    setCurEpisode(e.progress?.current_episode ?? 1);
    setSeasonData(e.media.season_episode_counts ?? null);
  }

  useEffect(() => {
    getEntry(entryId)
      .then(hydrate)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e)),
      );
  }, [entryId]);

  // Legacy backfill: entries added before per-season data was cached have
  // `media.season_episode_counts == null` — fetch it live, same read-only
  // enrichment pattern the preview page already uses. Best-effort: on
  // failure the editor just falls back to unconstrained number inputs.
  useEffect(() => {
    if (!entry || entry.media.type !== "series" || seasonData !== null) return;
    let cancelled = false;
    getMediaDetails(entry.media.source, entry.media.source_id, "series")
      .then((d) => {
        if (!cancelled && d.season_episode_counts) setSeasonData(d.season_episode_counts);
      })
      .catch(() => {
        /* no per-season data available — inputs stay unconstrained */
      });
    return () => {
      cancelled = true;
    };
  }, [entry, seasonData]);

  // Season 0 ("Specials") is excluded from progress tracking — same
  // aggregate TMDb's own seasons/episodes totals already exclude (spec §16).
  const regularSeasons = (seasonData ?? [])
    .filter((s) => s.season_number >= 1)
    .sort((a, b) => a.season_number - b.season_number);
  const finalSeasonNumber =
    regularSeasons.length > 0
      ? regularSeasons[regularSeasons.length - 1].season_number
      : null;
  const selectedSeasonInfo =
    curSeason === ""
      ? undefined
      : regularSeasons.find((s) => s.season_number === curSeason);
  const episodeCount = selectedSeasonInfo?.episode_count ?? null;
  const isFinalEpisodeOfFinalSeason =
    finalSeasonNumber !== null &&
    curSeason === finalSeasonNumber &&
    episodeCount !== null &&
    curEpisode === episodeCount;

  function selectSeason(season: number) {
    setCurSeason(season);
    setCurEpisode(1); // a season change starts fresh — never carries over an
    // episode number that might not exist in the new season
  }

  function selectEpisode(raw: number) {
    if (Number.isNaN(raw)) return;
    const max = episodeCount ?? undefined;
    setCurEpisode(Math.max(1, max ? Math.min(raw, max) : raw));
  }

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
      // seasons_completed is derived server-side from current_season — never
      // sent from here, so it can't drift out of sync with it (spec §16).
      const updated = await updateProgress(entryId, {
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

  async function advanceProgress() {
    if (curSeason === "" || curEpisode === "") return;
    setAdvancing(true);
    setError(null);
    setNotice(null);
    try {
      // S x, final episode -> S x+1, episode 1. Never invents a season beyond
      // the last one TMDb actually lists (spec §16 D4) — that case swaps this
      // button for "Mark as completed" instead, below.
      const rolloverToNextSeason = episodeCount !== null && curEpisode >= episodeCount;
      const nextSeason = rolloverToNextSeason ? curSeason + 1 : curSeason;
      const nextEpisode = rolloverToNextSeason ? 1 : curEpisode + 1;
      const updated = await updateProgress(entryId, {
        current_season: nextSeason,
        current_episode: nextEpisode,
      });
      hydrate(updated);
      setNotice(`Advanced to Season ${nextSeason} · Episode ${nextEpisode}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAdvancing(false);
    }
  }

  async function markSeriesCompleted() {
    setAdvancing(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateEntry(entryId, { status: "completed" });
      hydrate(updated);
      setNotice("Marked as completed.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAdvancing(false);
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

          {m.type === "series" && status !== "completed" && (
            <section className="entry__section">
              <p className="kicker">Progress</p>

              <div className="row" style={{ alignItems: "flex-end" }}>
                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="curSeason" className="field-label">
                    Season
                  </label>
                  {regularSeasons.length > 0 ? (
                    <select
                      id="curSeason"
                      value={curSeason === "" ? "" : curSeason}
                      onChange={(e) => selectSeason(Number(e.target.value))}
                      style={{ minWidth: "8rem" }}
                    >
                      {regularSeasons.map((s) => (
                        <option key={s.season_number} value={s.season_number}>
                          Season {s.season_number}
                        </option>
                      ))}
                    </select>
                  ) : (
                    // No per-season data available (fetch failed / non-TMDb
                    // source) — degrade to a plain, unconstrained number
                    // field rather than blocking progress tracking entirely.
                    <input
                      id="curSeason"
                      type="number"
                      min={1}
                      value={curSeason}
                      onChange={(e) =>
                        setCurSeason(e.target.value === "" ? "" : Number(e.target.value))
                      }
                      style={{ width: "6rem" }}
                    />
                  )}
                </div>

                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="curEpisode" className="field-label">
                    Episode
                  </label>
                  <div className="row" style={{ alignItems: "center", gap: "0.4rem" }}>
                    <input
                      id="curEpisode"
                      type="number"
                      min={1}
                      max={episodeCount ?? undefined}
                      value={curEpisode}
                      onChange={(e) =>
                        e.target.value === ""
                          ? setCurEpisode("")
                          : selectEpisode(Number(e.target.value))
                      }
                      style={{ width: "5rem" }}
                    />
                    <span className="muted">/ {episodeCount ?? "?"}</span>
                  </div>
                </div>
              </div>

              <div className="row" style={{ marginTop: "1rem", gap: "0.6rem" }}>
                <button onClick={saveProgress} disabled={saving || advancing}>
                  {saving ? "Saving…" : "Save"}
                </button>
                {isFinalEpisodeOfFinalSeason ? (
                  <button
                    type="button"
                    onClick={markSeriesCompleted}
                    disabled={saving || advancing}
                  >
                    {advancing ? "Saving…" : "Mark as completed"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={advanceProgress}
                    disabled={saving || advancing || curSeason === "" || curEpisode === ""}
                  >
                    {advancing ? "Advancing…" : "Advance"}
                  </button>
                )}
              </div>

              {regularSeasons.length > 0 && (
                <p className="muted" style={{ marginTop: "1rem", fontSize: "0.9rem" }}>
                  {regularSeasons
                    .map((s) => `Season ${s.season_number} · ${s.episode_count} eps`)
                    .join("  ·  ")}
                </p>
              )}
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
