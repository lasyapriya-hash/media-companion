"use client";

// Shared presentational pieces for media artwork + metadata. No data fetching,
// no state beyond a per-image "failed to load" flag. Used by every page so the
// collection, discovery, recommendations and detail views read as one journal.

import type { ReactNode } from "react";
import { useState } from "react";
import type { MediaItemOut, MediaType, NormalizedMedia } from "@/lib/api";

type AnyMedia = MediaItemOut | NormalizedMedia;

const KIND_LABEL: Record<MediaType, string> = {
  movie: "Film",
  series: "Series",
  book: "Book",
};

/** "5 seasons · 62 eps", or just the part we actually have. Never renders "?". */
export function seriesCount(
  seasons?: number | null,
  episodes?: number | null,
): string {
  const parts: string[] = [];
  if (seasons) parts.push(`${seasons} season${seasons === 1 ? "" : "s"}`);
  if (episodes) parts.push(`${episodes} eps`);
  return parts.join(" · ");
}

export function prettyLanguage(code?: string | null): string | null {
  if (!code) return null;
  const c = code.trim();
  if (!c) return null;
  if (c.length <= 3) return c.toUpperCase();
  return c[0].toUpperCase() + c.slice(1);
}

/** Human metadata fragments, in reading order. */
export function metaBits(m: AnyMedia): string[] {
  const bits: string[] = [KIND_LABEL[m.type] ?? m.type];
  if (m.year) bits.push(String(m.year));

  if (m.type === "movie" && m.runtime_minutes) {
    bits.push(`${m.runtime_minutes} min`);
  }
  if (m.type === "series") {
    if (m.seasons) bits.push(`${m.seasons} season${m.seasons === 1 ? "" : "s"}`);
    else if (m.episodes) bits.push(`${m.episodes} episodes`);
  }
  if (m.type === "book" && m.page_count) {
    bits.push(`${m.page_count} pages`);
  }

  const lang = prettyLanguage(m.language);
  if (lang) bits.push(lang);
  return bits;
}

export function MetaLine({
  media,
  className = "",
}: {
  media: AnyMedia;
  className?: string;
}) {
  const bits = metaBits(media);
  return (
    <div className={`metaline ${className}`.trim()}>
      <b>{bits[0]}</b>
      {bits.slice(1).map((b) => (
        <span key={b}> · {b}</span>
      ))}
    </div>
  );
}

export function Poster({
  media,
  className = "",
}: {
  media: AnyMedia;
  className?: string;
}) {
  const [broken, setBroken] = useState(false);
  const src = media.artwork_url;

  if (!src || broken) {
    return (
      <div className={`poster poster--ph ${className}`.trim()} aria-hidden>
        <span className="poster__kind">{KIND_LABEL[media.type] ?? media.type}</span>
        <span className="poster__title">{media.title}</span>
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className={`poster ${className}`.trim()}
      src={src}
      alt={`${media.title} cover art`}
      loading="lazy"
      onError={() => setBroken(true)}
    />
  );
}

/** Poster with optional rating / favourite pins overlaid. */
export function PosterFrame({
  media,
  rating,
  favourite,
}: {
  media: AnyMedia;
  rating?: number | null;
  favourite?: boolean;
}) {
  return (
    <div className="poster-frame">
      <Poster media={media} />
      {favourite && (
        <span className="pin pin--fav" title="Favourite">
          ★
        </span>
      )}
      {rating != null && (
        <span className="pin pin--rating" title="Your rating">
          {rating % 1 === 0 ? rating.toFixed(0) : rating.toFixed(1)}
        </span>
      )}
    </div>
  );
}

export function GenreTags({
  genres,
  kind,
  max = 4,
}: {
  genres: string[];
  kind?: MediaType;
  max?: number;
}) {
  const shown = genres.slice(0, max);
  if (!kind && shown.length === 0) return null;
  return (
    <div className="tags">
      {kind && <span className="tag tag--kind">{kind}</span>}
      {shown.map((g) => (
        <span key={g} className="tag">
          {g}
        </span>
      ))}
    </div>
  );
}

/**
 * Shared read-only presentation of a media item: poster + facts aside, then
 * title / byline / meta / genres / description / mood. `children` slots in the
 * page-specific block below — the tracking forms on the library detail page,
 * or the "Add to collection" action on the preview page. Used by both so the
 * detail experience is identical from every surface.
 */
export function MediaDetail({
  media,
  favourite = false,
  yourRating,
  children,
}: {
  media: AnyMedia;
  favourite?: boolean;
  /** Omit for a not-in-library preview; pass (number | null) for a library entry. */
  yourRating?: number | null;
  children?: ReactNode;
}) {
  const m = media;
  const lang = prettyLanguage(m.language);
  return (
    <div className="entry">
      <aside className="entry__aside">
        <div className="poster-link">
          <PosterFrame media={m} favourite={favourite} />
        </div>
        <dl className="facts">
          {yourRating !== undefined && (
            <div>
              <dt>Your rating</dt>
              <dd>{yourRating != null ? `${yourRating.toFixed(1)} / 10` : "—"}</dd>
            </div>
          )}
          {m.external_rating != null && (
            <div>
              <dt>Critics</dt>
              <dd>{m.external_rating.toFixed(1)} / 10</dd>
            </div>
          )}
          <div>
            <dt>Format</dt>
            <dd>{KIND_LABEL[m.type] ?? m.type}</dd>
          </div>
          {m.year && (
            <div>
              <dt>Year</dt>
              <dd>{m.year}</dd>
            </div>
          )}
          {lang && (
            <div>
              <dt>Language</dt>
              <dd>{lang}</dd>
            </div>
          )}
          {m.type === "movie" && m.runtime_minutes && (
            <div>
              <dt>Runtime</dt>
              <dd>{m.runtime_minutes} min</dd>
            </div>
          )}
          {m.type === "series" && (m.seasons || m.episodes) && (
            <div>
              <dt>Episodes</dt>
              <dd>{seriesCount(m.seasons, m.episodes)}</dd>
            </div>
          )}
          {m.type === "book" && m.page_count && (
            <div>
              <dt>Length</dt>
              <dd>{m.page_count} pages</dd>
            </div>
          )}
          {m.length_bucket && (
            <div>
              <dt>Pace</dt>
              <dd style={{ textTransform: "capitalize" }}>{m.length_bucket}</dd>
            </div>
          )}
        </dl>
      </aside>

      <div>
        <h1 className="entry__title">
          {m.title}
          {favourite ? " ★" : ""}
        </h1>
        {m.author && <p className="entry__byline">by {m.author}</p>}
        <MetaLine media={m} className="entry__meta" />

        {m.genres.length > 0 && (
          <div style={{ marginTop: "1rem" }}>
            <GenreTags genres={m.genres} kind={m.type} max={8} />
          </div>
        )}

        {m.description && <p className="entry__desc">{m.description}</p>}

        <div style={{ marginTop: "1.25rem" }}>
          <p className="field-label" style={{ marginBottom: "0.5rem" }}>
            Mood
          </p>
          {m.mood_tags.length > 0 ? (
            <div className="tags">
              {m.mood_tags.map((t) => (
                <span key={t} className="tag">
                  {t}
                </span>
              ))}
            </div>
          ) : (
            <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              Not yet classified.
            </p>
          )}
        </div>

        {children}
      </div>
    </div>
  );
}
