"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL, getHealth, type HealthResponse } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ok"; data: HealthResponse }
  | { kind: "error"; message: string };

export default function HomePage() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((data) => {
        if (!cancelled) setState({ kind: "ok", data });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>Personal Media Companion</h1>
      <p className="muted">
        One library for movies, series, and books &mdash; with natural-language
        recommendations.
      </p>

      <section className="panel" style={{ marginTop: "1.5rem" }}>
        <h2 style={{ marginTop: 0, fontSize: "1.05rem" }}>Backend connection</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          API base: <code>{API_BASE_URL}</code>
        </p>

        {state.kind === "loading" && <p>Checking&hellip;</p>}

        {state.kind === "ok" && (
          <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
            <li>
              Status:{" "}
              <span className="status-ok">{state.data.status}</span>
            </li>
            <li>
              Database:{" "}
              <span
                className={
                  state.data.database === "connected"
                    ? "status-ok"
                    : "status-err"
                }
              >
                {state.data.database}
              </span>
            </li>
            <li className="muted">Environment: {state.data.env}</li>
          </ul>
        )}

        {state.kind === "error" && (
          <p className="status-err">
            Could not reach the backend: {state.message}
          </p>
        )}
      </section>

      <p className="muted" style={{ marginTop: "2rem", fontSize: "0.9rem" }}>
        Phase 0 skeleton. Library, discovery, and recommendations arrive in
        later phases.
      </p>
    </main>
  );
}
