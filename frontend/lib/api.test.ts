import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  API_BASE_URL,
  getHealth,
  listLibrary,
  login,
  register,
  searchMedia,
} from "./api";
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
let assignMock: ReturnType<typeof vi.fn>;
let locationStub: { pathname: string; assign: (url: string) => void };

beforeEach(() => {
  assignMock = vi.fn();
  locationStub = { pathname: "/", assign: assignMock };
  vi.stubGlobal("window", {
    localStorage: makeMemoryStorage(),
    location: locationStub,
  });
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("token attachment", () => {
  it("attaches Authorization: Bearer <token> when a token is stored", async () => {
    setToken("my-jwt");
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "ok" }));

    await getHealth();

    const [, init] = fetchMock.mock.calls[0];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer my-jwt");
  });

  it("sends no Authorization header when no token is stored", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "ok" }));

    await getHealth();

    const [, init] = fetchMock.mock.calls[0];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("public requests remain usable without authentication", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    const result = await searchMedia("dune", "movie");

    expect(result).toEqual([]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/search?q=dune&type=movie`);
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });
});

describe("login / register JSON contracts", () => {
  it("login() posts {email, password} to /auth/login, no Authorization header", async () => {
    setToken("some-stray-token"); // must never be sent to /auth/*
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ access_token: "tok123", token_type: "bearer" }),
    );

    const result = await login("me@example.com", "hunter2222");

    expect(result).toEqual({ access_token: "tok123", token_type: "bearer" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/auth/login`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "me@example.com",
      password: "hunter2222",
    });
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("register() posts {email, password} to /auth/register and returns {id, email, created_at}", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "u1",
        email: "me@example.com",
        created_at: "2026-01-01T00:00:00Z",
      }),
    );

    const result = await register("me@example.com", "hunter2222");

    expect(result).toEqual({
      id: "u1",
      email: "me@example.com",
      created_at: "2026-01-01T00:00:00Z",
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/auth/register`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "me@example.com",
      password: "hunter2222",
    });
  });
});

describe("401 handling", () => {
  it("a 401 from a protected call clears the token and redirects to /login", async () => {
    setToken("stale-token");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Could not validate credentials" }, 401),
    );

    await expect(listLibrary()).rejects.toThrow(
      "Could not validate credentials",
    );

    expect(getToken()).toBeNull();
    expect(assignMock).toHaveBeenCalledWith("/login");
  });

  it("login's own 401 (bad credentials) does not clear a token or redirect (no loop)", async () => {
    setToken("still-valid-token");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Incorrect email or password" }, 401),
    );

    await expect(login("me@example.com", "wrong")).rejects.toThrow(
      "Incorrect email or password",
    );

    expect(getToken()).toBe("still-valid-token");
    expect(assignMock).not.toHaveBeenCalled();
  });

  it("register's own 401 does not clear a token or redirect", async () => {
    setToken("still-valid-token");
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "nope" }, 401));

    await expect(register("me@example.com", "wrong")).rejects.toThrow();

    expect(getToken()).toBe("still-valid-token");
    expect(assignMock).not.toHaveBeenCalled();
  });

  it("does not redirect again if already on /login (no redirect loop)", async () => {
    locationStub.pathname = "/login";
    setToken("stale-token");
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "..." }, 401));

    await expect(listLibrary()).rejects.toThrow();

    expect(getToken()).toBeNull(); // still cleared
    expect(assignMock).not.toHaveBeenCalled(); // but no further redirect
  });
});

describe("existing error behavior is preserved for non-401 failures", () => {
  it("a non-401 error response throws with the response's detail message", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Item is already in the library" }, 409),
    );

    await expect(listLibrary()).rejects.toThrow(
      "Item is already in the library",
    );
    expect(assignMock).not.toHaveBeenCalled();
  });

  it("a non-JSON error response falls back to a generic HTTP-status message", async () => {
    fetchMock.mockResolvedValueOnce(new Response("not json", { status: 500 }));

    await expect(listLibrary()).rejects.toThrow("Request failed (HTTP 500)");
  });

  it("a network failure throws the existing unreachable-server message", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("network down"));

    await expect(listLibrary()).rejects.toThrow("Could not reach the server.");
  });
});
