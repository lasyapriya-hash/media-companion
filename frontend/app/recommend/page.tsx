"use client";

import { useEffect, useState } from "react";
import {
  getRecommendations,
  getSurpriseRecommendations,
  getTasteProfile,
  type PreferenceObject,
  type RecommendationItem,
  type RecommendationResponse,
  type TasteProfile,
} from "@/lib/api";
import { GenreTags, MetaLine, Poster } from "@/components/media";

const EXAMPLES = [
  "Something cozy and light for a rainy Sunday evening",
  "A tense Korean thriller series, nothing too long",
  "Cerebral sci-fi books from the last few years",
  "A bittersweet slow-burn drama, ideally not too long",
];

function interpretation(p: PreferenceObject): string {
  const parts: string[] = [];
  if (p.media_type && p.media_type.length) parts.push(p.media_type.join(" / "));
  if (p.genres.length) parts.push(p.genres.join(", "));
  if (p.mood.length) parts.push(`${p.mood.join(", ")} in mood`);
  if (p.tone.length) parts.push(`${p.tone.join(", ")} in tone`);
  if (p.length) parts.push(`${p.length} length`);
  if (p.language.length) parts.push(p.language.join(", "));
  if (typeof p.release_period === "string") parts.push(p.release_period);
  if (p.avoid.length) parts.push(`avoiding ${p.avoid.join(", ")}`);
  return parts.length ? parts.join(" · ") : "an open-ended request";
}

/** One quiet sentence of derived taste context (no extra model call). */
function tasteSentence(t: TasteProfile | null): string | null {
  if (!t || t.favourite_genres.length === 0) return null;
  const g = t.favourite_genres[0].toLowerCase();
  const avg = t.avg_rating_by_genre[t.favourite_genres[0]];
  if (typeof avg === "number") {
    return `Based on your collection, you tend to rate ${g} highly — about ${avg.toFixed(
      1,
    )}/10 on average.`;
  }
  const langs = t.favourite_languages.slice(0, 1);
  if (langs.length) {
    return `Based on your collection, you gravitate toward ${g}, often in ${langs[0]}.`;
  }
  return `Based on your collection, you gravitate toward ${g}.`;
}

function AvailabilityNote({ item }: { item: RecommendationItem }) {
  if (item.media.type === "book") {
    return item.book_link ? (
      <p className="pick__avail">
        <a href={item.book_link} target="_blank" rel="noreferrer">
          Where to find it &rarr;
        </a>
      </p>
    ) : null;
  }
  const av = item.availability;
  if (!av || av.status !== "available") {
    return <p className="pick__avail">Streaming availability unknown in India.</p>;
  }
  const providers = [...av.flatrate, ...av.rent, ...av.buy];
  return (
    <p className="pick__avail">
      <b>In India:</b> {providers.slice(0, 4).join(", ")}
      {providers.length > 4 ? "…" : ""}
    </p>
  );
}

function Pick({ item, index }: { item: RecommendationItem; index: number }) {
  const lead = index === 0;
  return (
    <article className={lead ? "pick pick--lead" : "pick"}>
      <div className="poster-link">
        <Poster media={item.media} />
      </div>
      <div className="pick__body">
        <p className="pick__rank">
          {lead ? "The pick" : `Also — ${String(index + 1).padStart(2, "0")}`}
        </p>
        <h2 className="pick__title">{item.media.title}</h2>
        <MetaLine media={item.media} className="pick__meta" />
        <div className="pick__tags">
          <GenreTags genres={item.media.genres} kind={item.media.type} />
        </div>

        <div className="pick__why">
          <p className="pick__why-label">Why this</p>
          <p>{item.reason}</p>
        </div>

        {item.media.external_rating != null && (
          <p className="pick__avail">
            Critics&rsquo; score <b>{item.media.external_rating.toFixed(1)}</b> / 10
          </p>
        )}
        <AvailabilityNote item={item} />
      </div>
    </article>
  );
}

export default function RecommendPage() {
  const [text, setText] = useState("");
  const [resp, setResp] = useState<RecommendationResponse | null>(null);
  const [asked, setAsked] = useState("");
  const [surprised, setSurprised] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taste, setTaste] = useState<TasteProfile | null>(null);

  useEffect(() => {
    // Best-effort: powers the taste-context line; never blocks the page.
    getTasteProfile()
      .then(setTaste)
      .catch(() => undefined);
  }, []);

  async function submit(kind: "text" | "surprise") {
    setLoading(true);
    setError(null);
    setResp(null);
    try {
      if (kind === "surprise") {
        setResp(await getSurpriseRecommendations());
        setSurprised(true);
        setAsked("");
      } else {
        const q = text.trim();
        setResp(await getRecommendations(q));
        setSurprised(false);
        setAsked(q);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const tasteLine = tasteSentence(taste);

  return (
    <main>
      <section className="compose">
        <p className="kicker">Recommendations</p>
        <h1 className="compose__title">What are you in the mood for?</h1>
        <p className="compose__hint">
          Describe the feeling, the occasion, the constraints &mdash; the way
          you&rsquo;d tell a friend. No filters, no genre menus.
        </p>

        <form
          className="compose__field"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) submit("text");
          }}
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. a warm, funny film for a tired weeknight — nothing too heavy"
            rows={3}
            aria-label="Describe what you feel like watching or reading"
          />
          <div className="compose__actions">
            <button type="submit" disabled={loading || !text.trim()}>
              {loading ? "Finding something…" : "Recommend"}
            </button>
            {text && (
              <button
                type="button"
                className="ghost"
                onClick={() => setText("")}
                disabled={loading}
              >
                Clear
              </button>
            )}
            <button
              type="button"
              className="chip chip--surprise"
              onClick={() => submit("surprise")}
              disabled={loading}
              title="Pick something from your collection's tastes"
            >
              ✦ Surprise me
            </button>
          </div>
        </form>

        {!resp && (
          <div className="compose__examples">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                className="chip"
                onClick={() => setText(ex)}
                disabled={loading}
              >
                {ex}
              </button>
            ))}
          </div>
        )}
      </section>

      {error && <div className="error">{error}</div>}

      {resp && (
        <>
          <div className="note">
            <p className="note__label">
              {surprised
                ? "From your shelves"
                : resp.extraction === "llm"
                  ? "Read your note as"
                  : "Understood your note as"}
            </p>
            <p className="note__body">
              {surprised ? (
                <>A selection drawn from the tastes in your collection.</>
              ) : (
                <>
                  <q>{asked}</q> &mdash; {interpretation(resp.preferences)}.
                </>
              )}
            </p>
            {tasteLine && (
              <p className="note__taste">
                <span>✦</span>
                {tasteLine}
              </p>
            )}
          </div>

          {resp.results.length === 0 ? (
            <p className="empty">
              Nothing surfaced for that one. Try describing the mood or the
              occasion a little differently.
            </p>
          ) : (
            <div className="picks">
              {resp.results.map((item, i) => (
                <Pick
                  key={`${item.media.source}:${item.media.source_id}`}
                  item={item}
                  index={i}
                />
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}
