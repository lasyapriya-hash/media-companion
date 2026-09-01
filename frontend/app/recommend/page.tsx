"use client";

import { useState } from "react";
import {
  getRecommendations,
  type RecommendationItem,
  type RecommendationResponse,
} from "@/lib/api";

const EXAMPLES = [
  "Something cozy and light for a rainy Sunday evening",
  "A tense Korean thriller series, nothing too long",
  "Cerebral sci-fi books from the last few years",
];

function Availability({ item }: { item: RecommendationItem }) {
  if (item.media.type === "book") {
    return item.book_link ? (
      <a href={item.book_link} target="_blank" rel="noreferrer" className="muted">
        Access link &rarr;
      </a>
    ) : null;
  }
  const av = item.availability;
  if (!av || av.status !== "available") {
    return <span className="muted">Availability unknown (IN)</span>;
  }
  const providers = [...av.flatrate, ...av.rent, ...av.buy];
  return (
    <span className="muted">
      On {providers.slice(0, 3).join(", ")}
      {providers.length > 3 ? "…" : ""} (IN)
    </span>
  );
}

export default function RecommendPage() {
  const [text, setText] = useState("");
  const [resp, setResp] = useState<RecommendationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setResp(null);
    try {
      setResp(await getRecommendations(text.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>What do you feel like?</h1>
      <p className="muted">
        Describe the mood, situation, or constraints in your own words &mdash; no
        filters.
      </p>

      <form onSubmit={run} style={{ margin: "1rem 0 1.5rem" }}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. a bittersweet slow-burn drama, ideally not too long"
          rows={3}
          style={{ width: "100%", resize: "vertical" }}
          aria-label="Recommendation request"
        />
        <div className="row" style={{ marginTop: "0.75rem", flexWrap: "wrap" }}>
          <button type="submit" disabled={loading || !text.trim()}>
            {loading ? "Thinking…" : "Recommend"}
          </button>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              className="secondary"
              onClick={() => setText(ex)}
              disabled={loading}
            >
              {ex}
            </button>
          ))}
        </div>
      </form>

      {error && <div className="error-box">{error}</div>}

      {resp && (
        <>
          <p className="muted" style={{ marginBottom: "1rem" }}>
            Interpreted your request{" "}
            {resp.extraction === "llm"
              ? "with the language model"
              : "with the built-in parser"}
            {resp.preferences.genres.length > 0 &&
              ` · genres: ${resp.preferences.genres.join(", ")}`}
            {resp.preferences.mood.length > 0 &&
              ` · mood: ${resp.preferences.mood.join(", ")}`}
            {resp.preferences.avoid.length > 0 &&
              ` · avoiding: ${resp.preferences.avoid.join(", ")}`}
          </p>

          {resp.results.length === 0 && (
            <p className="muted">
              No matches came back. Try describing it a little differently.
            </p>
          )}

          <div className="card-grid">
            {resp.results.map((item) => (
              <div
                key={`${item.media.source}:${item.media.source_id}`}
                className="media-card"
              >
                <div
                  className="thumb"
                  style={
                    item.media.artwork_url
                      ? { backgroundImage: `url(${item.media.artwork_url})` }
                      : undefined
                  }
                />
                <div className="body">
                  <span className="title">{item.media.title}</span>
                  <div className="chips">
                    <span className="badge">{item.media.type}</span>
                    {item.media.year && (
                      <span className="badge">{item.media.year}</span>
                    )}
                    {item.media.length_bucket && (
                      <span className="badge">{item.media.length_bucket}</span>
                    )}
                  </div>
                  <span style={{ fontSize: "0.9rem" }}>{item.reason}</span>
                  <div style={{ marginTop: "auto", paddingTop: "0.5rem" }}>
                    <Availability item={item} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
