import { describe, expect, it } from "vitest";

import { evaluateGuard, isPublicPath } from "./auth-guard";

// Deliberately no `vi.stubGlobal("window", ...)` anywhere in this file —
// this is a plain-Node vitest environment with no `window`/`localStorage`
// global at all (the same situation as a server-rendering pass). If either
// function below ever reached for one, every test here would throw a
// ReferenceError before any assertion even ran.
describe("evaluateGuard / isPublicPath never touch window/localStorage", () => {
  it("run without throwing in an environment with no window at all", () => {
    expect(() => isPublicPath("/login")).not.toThrow();
    expect(() => evaluateGuard("/", false)).not.toThrow();
  });
});

describe("isPublicPath", () => {
  it("treats /login and /register as public", () => {
    expect(isPublicPath("/login")).toBe(true);
    expect(isPublicPath("/register")).toBe(true);
  });

  it("treats every existing application page as protected by default", () => {
    expect(isPublicPath("/")).toBe(false);
    expect(isPublicPath("/search")).toBe(false);
    expect(isPublicPath("/recommend")).toBe(false);
    expect(isPublicPath("/item/abc-123-uuid")).toBe(false);
    expect(isPublicPath("/item/preview")).toBe(false);
  });
});

describe("evaluateGuard", () => {
  it("no token on a protected route -> unauthenticated, and redirects", () => {
    const decision = evaluateGuard("/", false);
    expect(decision.authState).toBe("unauthenticated");
    expect(decision.shouldRedirect).toBe(true);
  });

  it("no token on every other protected page also redirects", () => {
    for (const path of ["/search", "/recommend", "/item/abc-123", "/item/preview"]) {
      expect(evaluateGuard(path, false).shouldRedirect).toBe(true);
    }
  });

  it("a token present on a protected route -> authenticated, no redirect", () => {
    const decision = evaluateGuard("/search", true);
    expect(decision.authState).toBe("authenticated");
    expect(decision.shouldRedirect).toBe(false);
  });

  it("/login and /register are never redirected, token or not", () => {
    expect(evaluateGuard("/login", false).shouldRedirect).toBe(false);
    expect(evaluateGuard("/login", true).shouldRedirect).toBe(false);
    expect(evaluateGuard("/register", false).shouldRedirect).toBe(false);
    expect(evaluateGuard("/register", true).shouldRedirect).toBe(false);
  });

  it("is stable/idempotent for the same inputs (no escalating redirect signal)", () => {
    const first = evaluateGuard("/", false);
    const second = evaluateGuard("/", false);
    expect(first).toEqual(second);
  });
});
