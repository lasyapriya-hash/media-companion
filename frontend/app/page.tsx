"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  listLibrary,
  STATUS_LABELS,
  type LibraryEntryOut,
  type LibraryStatus,
  type MediaType,
} from "@/lib/api";
import { PosterFrame, metaBits } from "@/components/media";

const STATUSES: LibraryStatus[] = ["want", "in_progress", "completed", "dropped"];
const TYPES: MediaType[] = ["movie", "series", "book"];

// Order + headings for the understated shelf grouping.
const GROUPS: { key: LibraryStatus; label: string }[] = [
  { key: "in_progress", label: "Currently watching & reading" },
  { key: "want", label: "Want to get to" },
  { key: "completed", label: "Finished" },
  { key: "dropped", label: "Set aside" },
];

function summarise(entries: LibraryEntryOut[]): string {
  if (entries.length === 0) return "";
  const n = entries.length;
  const favs = entries.filter((e) => e.favourite).length;
  const done = entries.filter((e) => e.status === "completed").length;
  const parts = [`${n} ${n === 1 ? "title" : "titles"}`];
  if (done) parts.push(`${done} finished`);
  if (favs) parts.push(`${favs} ${favs === 1 ? "favourite" : "favourites"}`);
  return parts.join("  ·  ");
}

function Tile({
  entry,
  grouped = false,
}: {
  entry: LibraryEntryOut;
  grouped?: boolean;
}) {
  const m = entry.media;
  const seasonsIn = entry.progress?.seasons_completed ?? 0;
  const showProgress = m.type === "series" && seasonsIn > 0;
  return (
    <Link href={`/item/${entry.id}`} className="shelf__item poster-link">
      <PosterFrame
        media={m}
        rating={entry.rating}
        favourite={entry.favourite}
      />
      <div>
        <div className="caption__title">{m.title}</div>
        <div className="caption__meta">{metaBits(m).join(" · ")}</div>
        {/* In a grouped view the section heading already states the status, so
            keep the caption to a quiet colour dot (+ progress). */}
        {(!grouped || showProgress) && (
          <div className="caption__foot">
            <span className={`dot dot--${entry.status}`} />
            {grouped ? (
              showProgress && (
                <span>
                  {seasonsIn} season{seasonsIn === 1 ? "" : "s"} in
                </span>
              )
            ) : (
              <>
                <span>{STATUS_LABELS[entry.status]}</span>
                {showProgress && (
                  <span>
                    · {seasonsIn} season{seasonsIn === 1 ? "" : "s"} in
                  </span>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </Link>
  );
}

export default function CollectionPage() {
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

  const count = useMemo(() => summarise(entries ?? []), [entries]);
  const filtered = statusFilter !== "" || typeFilter !== "";

  // Group into shelves only on the unfiltered view, and only when there's
  // enough spread to be worth it (>= 2 non-empty status groups). Otherwise a
  // single flat wall keeps the "one shelf" feeling.
  const grouped = useMemo(() => {
    if (!entries || filtered) return null;
    const byStatus = GROUPS.map((g) => ({
      ...g,
      items: entries.filter((e) => e.status === g.key),
    })).filter((g) => g.items.length > 0);
    return byStatus.length >= 2 && entries.length >= 4 ? byStatus : null;
  }, [entries, filtered]);

  return (
    <main>
      <div className="page-head">
        <p className="kicker">Your library</p>
        <h1 className="page-title">The Collection</h1>
        <p className="page-sub">
          Everything you&rsquo;re watching, reading, and meaning to get to &mdash;
          films, series, and books in one place.
        </p>
        {count && <p className="count-line">{count}</p>}
      </div>

      <div className="filters">
        <label>
          Status
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
        <label>
          Format
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as MediaType | "")}
          >
            <option value="">All</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t[0].toUpperCase() + t.slice(1)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <div className="error">{error}</div>}
      {!entries && !error && <p className="muted">Gathering your shelves&hellip;</p>}

      {entries && entries.length === 0 && (
        <div className="empty">
          <p style={{ marginTop: 0 }}>
            {filtered
              ? "Nothing here under those filters."
              : "Your collection is empty for now."}
          </p>
          <Link href="/search">Find something to add &rarr;</Link>
        </div>
      )}

      {entries && entries.length > 0 && grouped && (
        <>
          {grouped.map((g) => (
            <section key={g.key} className="shelf-group">
              <h2 className="shelf-group__label">
                {g.label} <span>· {g.items.length}</span>
              </h2>
              <div className="shelf">
                {g.items.map((entry) => (
                  <Tile key={entry.id} entry={entry} grouped />
                ))}
              </div>
            </section>
          ))}
        </>
      )}

      {entries && entries.length > 0 && !grouped && (
        <div className="shelf">
          {entries.map((entry) => (
            <Tile key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </main>
  );
}
