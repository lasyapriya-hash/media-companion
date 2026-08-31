"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  listLibrary,
  STATUS_LABELS,
  type LibraryEntryOut,
  type LibraryStatus,
  type MediaType,
} from "@/lib/api";

const STATUSES: LibraryStatus[] = [
  "want",
  "in_progress",
  "completed",
  "dropped",
];
const TYPES: MediaType[] = ["movie", "series", "book"];

export default function LibraryPage() {
  const [entries, setEntries] = useState<LibraryEntryOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<LibraryStatus | "">("");
  const [typeFilter, setTypeFilter] = useState<MediaType | "">("");

  const load = useCallback(() => {
    setError(null);
    setEntries(null);
    listLibrary({
      status: statusFilter || undefined,
      type: typeFilter || undefined,
    })
      .then(setEntries)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e)),
      );
  }, [statusFilter, typeFilter]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <main>
      <h1>Your library</h1>

      <div className="row" style={{ margin: "1rem 0 1.5rem" }}>
        <label className="muted">
          Status{" "}
          <select
            value={statusFilter}
            onChange={(e) =>
              setStatusFilter(e.target.value as LibraryStatus | "")
            }
          >
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="muted">
          Type{" "}
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as MediaType | "")}
          >
            <option value="">All</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <div className="error-box">{error}</div>}

      {!entries && !error && <p className="muted">Loading&hellip;</p>}

      {entries && entries.length === 0 && (
        <div className="panel">
          <p style={{ marginTop: 0 }}>Nothing here yet.</p>
          <Link href="/search">Search for something to add &rarr;</Link>
        </div>
      )}

      {entries && entries.length > 0 && (
        <div className="card-grid">
          {entries.map((entry) => (
            <Link
              key={entry.id}
              href={`/item/${entry.id}`}
              className="media-card"
              style={{ color: "inherit" }}
            >
              <div
                className="thumb"
                style={
                  entry.media.artwork_url
                    ? { backgroundImage: `url(${entry.media.artwork_url})` }
                    : undefined
                }
              />
              <div className="body">
                <span className="title">
                  {entry.media.title}
                  {entry.favourite ? " ★" : ""}
                </span>
                <div className="chips">
                  <span className="badge">{entry.media.type}</span>
                  {entry.media.year && (
                    <span className="badge">{entry.media.year}</span>
                  )}
                  <span className="badge">
                    {STATUS_LABELS[entry.status]}
                  </span>
                </div>
                {entry.rating != null && (
                  <span className="muted">Your rating: {entry.rating}/10</span>
                )}
                {entry.media.type === "series" && entry.progress && (
                  <span className="muted">
                    {entry.progress.seasons_completed} season
                    {entry.progress.seasons_completed === 1 ? "" : "s"} done
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
