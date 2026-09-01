"use client";

import { useState } from "react";
import {
  addToLibrary,
  searchMedia,
  type MediaType,
  type NormalizedMedia,
} from "@/lib/api";
import { GenreTags, MetaLine, Poster } from "@/components/media";

const TYPE_OPTIONS: { value: MediaType | ""; label: string }[] = [
  { value: "", label: "Everything" },
  { value: "movie", label: "Films" },
  { value: "series", label: "Series" },
  { value: "book", label: "Books" },
];

function resultKey(m: NormalizedMedia) {
  return `${m.source}:${m.source_id}`;
}

export default function DiscoverPage() {
  const [query, setQuery] = useState("");
  const [type, setType] = useState<MediaType | "">("");
  const [results, setResults] = useState<NormalizedMedia[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<Record<string, string>>({});

  async function runSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      setResults(await searchMedia(query.trim(), type || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function add(m: NormalizedMedia) {
    const key = resultKey(m);
    setAdded((a) => ({ ...a, [key]: "adding" }));
    try {
      await addToLibrary(m);
      setAdded((a) => ({ ...a, [key]: "added" }));
    } catch (err) {
      setAdded((a) => ({
        ...a,
        [key]: err instanceof Error ? err.message : "Could not add",
      }));
    }
  }

  return (
    <main>
      <div className="page-head">
        <p className="kicker">Add to your library</p>
        <h1 className="page-title">Discover</h1>
        <p className="page-sub">
          Search films and series from TMDb and books from Open Library, then
          keep what you want on your shelves.
        </p>
      </div>

      <form onSubmit={runSearch} className="searchbar" style={{ marginBottom: "2rem" }}>
        <input
          type="search"
          placeholder="A title, an author, a keyword…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search query"
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value as MediaType | "")}
          aria-label="Media type"
        >
          {TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <button type="submit" disabled={loading || !query.trim()}>
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {error && <div className="error">{error}</div>}
      {results && results.length === 0 && (
        <p className="empty">No matches. Try another spelling or a broader term.</p>
      )}

      {results && results.length > 0 && (
        <div className="shelf">
          {results.map((m) => {
            const key = resultKey(m);
            const state = added[key];
            return (
              <div key={key} className="shelf__item">
                <div className="poster-link">
                  <Poster media={m} />
                </div>
                <div>
                  <div className="caption__title">{m.title}</div>
                  <MetaLine media={m} className="caption__meta" />
                  {m.author && (
                    <div className="caption__meta">by {m.author}</div>
                  )}
                </div>
                {m.genres.length > 0 && (
                  <GenreTags genres={m.genres} max={3} />
                )}
                <div style={{ marginTop: "auto", paddingTop: "0.3rem" }}>
                  {state === "added" ? (
                    <span className="status-ok">✓ In your collection</span>
                  ) : state && state !== "adding" ? (
                    <span className="status-err">{state}</span>
                  ) : (
                    <button
                      className="ghost"
                      disabled={state === "adding"}
                      onClick={() => add(m)}
                    >
                      {state === "adding" ? "Adding…" : "Add to collection"}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
