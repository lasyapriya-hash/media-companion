"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { hasToken } from "@/lib/auth";
import { evaluateGuard, isPublicPath, type AuthState } from "@/lib/auth-guard";

/**
 * Shared route guard (Phase 8.4C), mounted once in the root layout around
 * `{children}`. /login and /register always render immediately — never
 * gated, never shown a "checking" state, and never redirected. Every other
 * route waits for the client-only token check before rendering anything,
 * so a protected page is never even briefly visible to a signed-out
 * visitor (the SSR/hydration pass — where `window` doesn't exist yet —
 * always starts at "checking", never "authenticated").
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
  const [authState, setAuthState] = useState<AuthState>("checking");

  useEffect(() => {
    const decision = evaluateGuard(pathname, hasToken());
    setAuthState(decision.authState);
    if (decision.shouldRedirect) {
      router.replace("/login");
    }
  }, [pathname, router]);

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
