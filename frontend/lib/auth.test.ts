import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearToken, getToken, hasToken, setToken } from "./auth";

/** A minimal in-memory `Storage` — enough for `localStorage`'s surface,
 * without needing jsdom just to exercise this module. */
function makeMemoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
  } as Storage;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("in a browser context", () => {
  beforeEach(() => {
    vi.stubGlobal("window", { localStorage: makeMemoryStorage() });
  });

  it("returns null / false when nothing is stored", () => {
    expect(getToken()).toBeNull();
    expect(hasToken()).toBe(false);
  });

  it("round-trips set -> get -> clear", () => {
    setToken("abc.def.ghi");
    expect(getToken()).toBe("abc.def.ghi");
    expect(hasToken()).toBe(true);

    clearToken();
    expect(getToken()).toBeNull();
    expect(hasToken()).toBe(false);
  });

  it("setToken overwrites a previously stored token", () => {
    setToken("first-token");
    setToken("second-token");
    expect(getToken()).toBe("second-token");
  });
});

describe("during server rendering (no window)", () => {
  // Deliberately does NOT stub `window` — matches the real SSR pass, where
  // it genuinely doesn't exist yet.
  it("every accessor is a safe no-op instead of throwing", () => {
    expect(getToken()).toBeNull();
    expect(hasToken()).toBe(false);
    expect(() => setToken("x")).not.toThrow();
    expect(() => clearToken()).not.toThrow();
  });
});
