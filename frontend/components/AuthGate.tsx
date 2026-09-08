"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth-context";
import { deriveAuthState, evaluateGuard, isPublicPath } from "@/lib/auth-guard";

/**
 * Shared route guard (Phase 8.4C; reads shared auth state as of 8.4D),
 * mounted once in the root layout around `{children}`. /login and
 * /register always render immediately — never gated, never shown a
 * "checking" state, and never redirected. Every other route waits for the
 * client-only token check before rendering anything, so a protected page
 * is never even briefly visible to a signed-out visitor (the SSR/hydration
 * pass — where `window` doesn't exist yet — always starts at "checking",
 * never "authenticated").
 *
 * Reads `isAuthenticated`/`checked` from `AuthProvider` (lib/auth-context)
 * rather than checking the token itself — the same state `SiteNav` reads,
 * so the two can never disagree, and so a login on /login or a logout from
 * SiteNav is reflected here immediately rather than only on the next
 * pathname change.
 *
 * Only checks whether a token is *present*; never decodes or validates it.
 * An expired/rejected-but-present token is a separate case, handled after
 * this gate lets the page through: `lib/api.ts`'s `request()` already
 * clears the token and redirects on a 401 from the backend (Phase 8.4A).
 * The two never fight over the redirect — this gate only ever acts when
 * there is no token at all.
 */
export default function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, checked } = useAuth();

  const authState = deriveAuthState(checked, isAuthenticated);

  useEffect(() => {
    // Never redirect before the initial check has actually run — the
    // default `isAuthenticated: false` before then isn't a real "no
    // token" verdict yet.
    if (!checked) return;
    if (evaluateGuard(pathname, isAuthenticated).shouldRedirect) {
      router.replace("/login");
    }
  }, [pathname, checked, isAuthenticated, router]);

  if (isPublicPath(pathname) || authState === "authenticated") {
    return <>{children}</>;
  }

  return (
    <main>
      <p className="muted">
        {authState === "checking"
          ? "Checking your session…"
          : "Redirecting to login…"}
      </p>
    </main>
  );
}
