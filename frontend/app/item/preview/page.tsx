"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { addToLibrary, parsePreviewMedia } from "@/lib/api";
import { MediaDetail } from "@/components/media";

function PreviewInner() {
  const params = useSearchParams();
  const router = useRouter();
  const media = useMemo(() => parsePreviewMedia(params.get("m")), [params]);

  const [state, setState] = useState<"idle" | "adding" | "exists">("idle");
  const [error, setError] = useState<string | null>(null);

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
