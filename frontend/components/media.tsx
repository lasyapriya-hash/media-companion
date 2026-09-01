"use client";

// Shared presentational pieces for media artwork + metadata. No data fetching,
// no state beyond a per-image "failed to load" flag. Used by every page so the
// collection, discovery, recommendations and detail views read as one journal.

import { useState } from "react";
import type { MediaItemOut, MediaType, NormalizedMedia } from "@/lib/api";

type AnyMedia = MediaItemOut | NormalizedMedia;

const KIND_LABEL: Record<MediaType, string> = {
  movie: "Film",
  series: "Series",
  book: "Book",
};

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
