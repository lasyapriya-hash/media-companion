import path from "node:path";
import { defineConfig } from "vitest/config";

// Plain Node environment — this project has no DOM-rendering tests, only
// the auth/token plumbing (Phase 8.4A), which is exercised via a small
// hand-rolled `window`/`localStorage` stub per test (see lib/auth.test.ts,
// lib/api.test.ts). No jsdom dependency needed.
export default defineConfig({
  test: {
    environment: "node",
    include: ["**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
