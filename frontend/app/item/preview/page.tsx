"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  addToLibrary,
  getMediaDetails,
  parsePreviewMedia,
  type NormalizedMedia,
} from "@/lib/api";
import { MediaDetail } from "@/components/media";

/** List endpoints omit runtime / season counts; fill them from the details
 *  call when they're missing. Never overwrites a value the list already had. */
const ENRICH_KEYS = [
  "runtime_minutes",
  "seasons",
  "episodes",
  "episode_runtime_minutes",
  "length_bucket",
  "description",
] as const;

function PreviewInner() {
  const params = useSearchParams();
  const router = useRouter();
  const base = useMemo(() => parsePreviewMedia(params.get("m")), [params]);
  const [media, setMedia] = useState<NormalizedMedia | null>(base);

  const [state, setState] = useState<"idle" | "adding" | "exists">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setMedia(base);
    if (!base) return;
    const missing = ENRICH_KEYS.some((k) => base[k] == null);
    if (!missing || (base.type !== "movie" && base.type !== "series")) return;
    let live = true;
    getMediaDetails(base.source, base.source_id, base.type)
      .then((full) => {
        if (!live) return;
        setMedia((cur) => {
          if (!cur) return cur;
          const next: Record<string, unknown> = { ...cur };
          const src = full as unknown as Record<string, unknown>;
          for (const k of ENRICH_KEYS) {
            if (next[k] == null && src[k] != null) next[k] = src[k];
          }
          return next as unknown as NormalizedMedia;
        });
      })
      .catch(() => undefined); // best-effort; keep the list-level fields
    return () => {
      live = false;
    };
  }, [base]);

  if (!media) {
    return (
      <main>
        <p className="empty">
          Nothing to preview here. Open a title from{" "}
          <Link href="/search">Discover</Link> or{" "}
          <Link href="/recommend">Recommend</Link>.
        </p>
      </main>
    );
  }

  async function add() {
    if (!media) return;
    setState("adding");
    setError(null);
    try {
      const entry = await addToLibrary(media);
      // Land on the real, editable library detail page.
      router.replace(`/item/${entry.id}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.toLowerCase().includes("already")) setState("exists");
      else {
        setState("idle");
        setError(msg);
      }
    }
  }

  return (
    <main>
      <button
        type="button"
        className="backlink"
        onClick={() => router.back()}
      >
        &larr; Back
      </button>

      <MediaDetail media={media}>
        <section className="entry__section">
          <p className="kicker">Not in your collection</p>
          <p className="muted" style={{ marginTop: 0 }}>
            Add it to track status, rating, and notes.
          </p>
          {state === "exists" ? (
            <p className="notice" role="status">
              Already in your collection &mdash;{" "}
              <Link href="/">open it from The Collection</Link>.
            </p>
          ) : (
            <button onClick={add} disabled={state === "adding"}>
              {state === "adding" ? "Adding…" : "Add to collection"}
            </button>
          )}
          {error && <div className="error">{error}</div>}
        </section>
      </MediaDetail>
    </main>
  );
}

export default function PreviewPage() {
  return (
    <Suspense fallback={<p className="muted">Opening the page&hellip;</p>}>
      <PreviewInner />
    </Suspense>
  );
}
