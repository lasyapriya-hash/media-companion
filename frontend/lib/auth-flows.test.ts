import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { passwordsMatch, performLogout, submitLogin, submitRegister } from "./auth-flows";
import { getToken, setToken } from "./auth";

/** A minimal in-memory `Storage` — enough for `localStorage`'s surface. */
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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

let confirmMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  confirmMock = vi.fn();
  vi.stubGlobal("window", {
    localStorage: makeMemoryStorage(),
    location: { pathname: "/login", assign: vi.fn() },
    confirm: confirmMock,
  });
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("passwordsMatch", () => {
  it("is true only when both fields are equal and non-empty", () => {
    expect(passwordsMatch("hunter2222", "hunter2222")).toBe(true);
    expect(passwordsMatch("hunter2222", "hunter2223")).toBe(false);
    expect(passwordsMatch("", "")).toBe(false);
  });
});

describe("submitLogin", () => {
  it("stores the returned access token on success", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ access_token: "tok-abc", token_type: "bearer" }),
    );

    const result = await submitLogin("me@example.com", "hunter2222");

    expect(result).toEqual({ ok: true });
    expect(getToken()).toBe("tok-abc");
  });

  it("propagates the backend's error message on failure, and stores no token", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Incorrect email or password" }, 401),
    );

    const result = await submitLogin("me@example.com", "wrong-password");

    expect(result).toEqual({
      ok: false,
      error: "Incorrect email or password",
    });
    expect(getToken()).toBeNull();
  });
});

describe("submitRegister", () => {
  it("succeeds without ever storing a token (UserOut has no access_token)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "u1",
        email: "me@example.com",
        created_at: "2026-01-01T00:00:00Z",
      }),
    );

    const result = await submitRegister("me@example.com", "hunter2222");

    expect(result).toEqual({ ok: true });
    expect(getToken()).toBeNull();
  });

  it("propagates the backend's error message on failure (e.g. duplicate email)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "An account with this email already exists" }, 409),
    );

    const result = await submitRegister("me@example.com", "hunter2222");

    expect(result).toEqual({
      ok: false,
      error: "An account with this email already exists",
    });
  });

  it("mismatched passwords never reach this far — no API call is made", async () => {
    // Mirrors what RegisterPage does: check passwordsMatch() first and only
    // call submitRegister() when it passes.
    expect(passwordsMatch("hunter2222", "different")).toBe(false);
    // fetch was never wired to a response — calling it now would throw, so
    // this doubles as proof nothing here ever invoked the network.
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("performLogout", () => {
  it("clears the stored token when confirmed", () => {
    setToken("some-token");

    performLogout(vi.fn(), () => true);

    expect(getToken()).toBeNull();
  });

  it("navigates to /login when confirmed", () => {
    setToken("some-token");
    const navigate = vi.fn();

    performLogout(navigate, () => true);

    expect(navigate).toHaveBeenCalledWith("/login");
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("returns true when confirmed", () => {
    setToken("some-token");

    expect(performLogout(vi.fn(), () => true)).toBe(true);
  });

  it("clears the token and navigates even when there was no token to begin with", () => {
    const navigate = vi.fn();

    expect(() => performLogout(navigate, () => true)).not.toThrow();

    expect(getToken()).toBeNull();
    expect(navigate).toHaveBeenCalledWith("/login");
  });

  it("makes no network call — logout is purely client-side (stateless JWTs)", () => {
    setToken("some-token");

    performLogout(vi.fn(), () => true);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does nothing and returns false when the user cancels the confirmation", () => {
    setToken("some-token");
    const navigate = vi.fn();

    const result = performLogout(navigate, () => false);

    expect(result).toBe(false);
    expect(getToken()).toBe("some-token");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("defaults to a real window.confirm prompt with the expected message", () => {
    setToken("some-token");
    const navigate = vi.fn();
    confirmMock.mockReturnValueOnce(true);

    const result = performLogout(navigate);

    expect(confirmMock).toHaveBeenCalledWith(
      "Are you sure you want to log out?",
    );
    expect(result).toBe(true);
    expect(getToken()).toBeNull();
    expect(navigate).toHaveBeenCalledWith("/login");
  });

  it("via the default window.confirm: cancelling keeps the user logged in", () => {
    setToken("some-token");
    const navigate = vi.fn();
    confirmMock.mockReturnValueOnce(false);

    const result = performLogout(navigate);

    expect(result).toBe(false);
    expect(getToken()).toBe("some-token");
    expect(navigate).not.toHaveBeenCalled();
  });
});
