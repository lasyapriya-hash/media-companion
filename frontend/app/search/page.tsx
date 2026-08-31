"use client";

import { useState } from "react";
import {
  addToLibrary,
  searchMedia,
  type MediaType,
  type NormalizedMedia,
} from "@/lib/api";

const TYPE_OPTIONS: { value: MediaType | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "movie", label: "Movies" },
  { value: "series", label: "Series" },
  { value: "book", label: "Books" },
];

function resultKey(m: NormalizedMedia) {
  return `${m.source}:${m.source_id}`;
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [type, setType] = useState<MediaType | "">("");
  const [results, setResults] = useState<NormalizedMedia[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<Record<string, string>>({}); // key -> "added" | error

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
        [key]: err instanceof Error ? err.message : "Failed to add",
      }));
    }
  }

  return (
    <main>
      <h1>Search &amp; add</h1>

      <form onSubmit={runSearch} className="row" style={{ marginBottom: "1.5rem" }}>
        <input
          type="search"
          placeholder="Title, author, keyword…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ flex: "1 1 240px" }}
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

      {error && <div className="error-box">{error}</div>}

      {results && results.length === 0 && (
        <p className="muted">No results.</p>
      )}

      {results && results.length > 0 && (
        <div className="card-grid">
          {results.map((m) => {
            const key = resultKey(m);
            const state = added[key];
            return (
              <div key={key} className="media-card">
                <div
                  className="thumb"
                  style={
                    m.artwork_url
                      ? { backgroundImage: `url(${m.artwork_url})` }
                      : undefined
                  }
                />
                <div className="body">
                  <span className="title">{m.title}</span>
                  <div className="chips">
                    <span className="badge">{m.type}</span>
                    {m.year && <span className="badge">{m.year}</span>}
                    {m.length_bucket && (
                      <span className="badge">{m.length_bucket}</span>
                    )}
                  </div>
                  {m.author && <span className="muted">{m.author}</span>}
                  {m.description && (
                    <span className="muted" style={{ fontSize: "0.85rem" }}>
                      {m.description.slice(0, 140)}
                      {m.description.length > 140 ? "…" : ""}
                    </span>
                  )}
                  <div style={{ marginTop: "auto", paddingTop: "0.5rem" }}>
                    {state === "added" ? (
                      <span className="status-ok">✓ Added</span>
                    ) : state && state !== "adding" ? (
                      <span className="status-err">{state}</span>
                    ) : (
                      <button
                        className="secondary"
                        disabled={state === "adding"}
                        onClick={() => add(m)}
                      >
                        {state === "adding" ? "Adding…" : "Add to library"}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
