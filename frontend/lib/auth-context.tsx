"use client";

// Shared auth state (Phase 8.4D) — the smallest thing that lets two
// separate sibling components (SiteNav, AuthGate) agree on "is there a
// token right now" without prop-drilling through the server-rendered root
// layout, and without pulling in a state-management library. This is
// nothing more than React's own Context, mounted once from a single client
// wrapper around both of them (see app/layout.tsx) — not a new dependency,
// not a new pattern beyond what AuthGate already established in Phase
// 8.4C.
//
// Why a shared store is needed at all: writing to localStorage does NOT
// fire a same-tab `storage` event (only other tabs see that), so without
// this, SiteNav would have no way to find out a login/logout just
// happened in the same tab. `refresh()`/`logout()` below are the explicit,
// deterministic triggers instead — login calls `refresh()` right after
// storing the token, and `logout()` clears it (once the user confirms —
// see `performLogout`), synchronously updating this shared state before
// anything navigates. Cancelling the confirmation leaves this state, and
// the stored token, untouched.

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { hasToken } from "@/lib/auth";
import { performLogout } from "@/lib/auth-flows";

interface AuthContextValue {
  /** Whether a token is currently stored. Only meaningful once `checked`
   * is true — see lib/auth-guard.ts's `deriveAuthState`. */
  isAuthenticated: boolean;
  /** False only during the brief window before the first client-side
   * check has run (the SSR/hydration pass, where `localStorage` doesn't
   * exist yet). */
  checked: boolean;
  /** Re-read the stored token and update `isAuthenticated`. Call this
   * right after a successful login, so every subscriber picks up the
   * change immediately rather than waiting for some other trigger. */
  refresh: () => void;
  /** Ask for confirmation, then — only if confirmed — clear the token and
   * navigate to /login. A cancelled confirmation leaves the session as-is. */
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [checked, setChecked] = useState(false);

  const refresh = useCallback(() => {
    setIsAuthenticated(hasToken());
    setChecked(true);
  }, []);

  // The one-time initial check — mirrors what AuthGate did on its own in
  // Phase 8.4C, just lifted up here so SiteNav sees the same result.
  useEffect(() => {
    refresh();
  }, [refresh]);

  const logout = useCallback(() => {
    // Only flip to unauthenticated if the user actually confirmed — a
    // cancelled prompt must leave the session untouched (performLogout
    // returns false without clearing the token or navigating in that case).
    if (performLogout(router.push)) {
      setIsAuthenticated(false);
    }
  }, [router]);

  return (
    <AuthContext.Provider value={{ isAuthenticated, checked, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth() must be used within an <AuthProvider>.");
  }
  return ctx;
}
