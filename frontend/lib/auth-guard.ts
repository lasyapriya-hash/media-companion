// Route-guard decision logic (Phase 8.4C), kept separate from the
// component that renders it — same reasoning as lib/auth-flows.ts: a plain
// function with no `window`/`localStorage` reference of its own is trivial
// to test without rendering anything, and trivially safe to call during
// server rendering (there is nothing here that *could* reach for browser
// globals — the caller reads the token, only inside an effect, and passes
// the result in).
//
// Public routes are allow-listed rather than protected routes being
// deny-listed: any route not explicitly listed here defaults to protected,
// so a page added later is guarded unless someone deliberately opts it out.

export type AuthState = "checking" | "authenticated" | "unauthenticated";

const PUBLIC_PATHS = ["/login", "/register"];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

export interface GuardDecision {
  /** What the gate should render for. */
  authState: AuthState;
  /** Whether the gate should send the browser to /login right now. */
  shouldRedirect: boolean;
}

/**
 * Pure decision: given the current path and whether a token is currently
 * stored, decide what to show and whether to redirect. Only checks
 * *presence* of a token — never decodes or validates it (the backend
 * remains the authority on that; an expired/rejected token is instead
 * caught by `lib/api.ts`'s `request()` 401 handler, after this gate has
 * already let the page through).
 */
export function evaluateGuard(
  pathname: string,
  tokenPresent: boolean,
): GuardDecision {
  return {
    authState: tokenPresent ? "authenticated" : "unauthenticated",
    shouldRedirect: !tokenPresent && !isPublicPath(pathname),
  };
}
