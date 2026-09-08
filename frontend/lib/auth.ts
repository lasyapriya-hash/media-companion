// Client-side JWT storage (Phase 8.4A).
//
// localStorage is the approved strategy for this project: the whole app is
// client-rendered ("use client" on every page, no middleware, no Server
// Actions calling the backend), so there is no server-side code path that
// ever needs this token — see the Phase 8.4 audit. Every accessor below
// guards against running during server rendering, where `window` (and so
// `localStorage`) doesn't exist yet.

const TOKEN_STORAGE_KEY = "media-companion:auth-token";

function hasStorage(): boolean {
  return typeof window !== "undefined" && !!window.localStorage;
}

/** The stored JWT, or `null` if there isn't one (or during server rendering). */
export function getToken(): string | null {
  if (!hasStorage()) return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

/** Persist a JWT after a successful login. No-op during server rendering. */
export function setToken(token: string): void {
  if (!hasStorage()) return;
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

/** Remove the stored JWT (logout, or a session that's expired/been rejected). */
export function clearToken(): void {
  if (!hasStorage()) return;
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

/** Whether a token is currently stored — not a guarantee it's still valid. */
export function hasToken(): boolean {
  return getToken() !== null;
}
