// Login/register submit logic (Phase 8.4B), kept separate from the page
// components so it can be unit-tested directly — same reasoning as
// lib/api.ts/lib/auth.ts in Phase 8.4A: plain functions are easy to test
// without rendering anything. Pages call these and react to the result
// (navigate on success, show `error` on failure); neither function
// navigates itself, since a plain module has no router to navigate with.

import { login, register } from "@/lib/api";
import { setToken } from "@/lib/auth";

export type AuthFlowResult = { ok: true } | { ok: false; error: string };

function messageFor(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Client-side check only — the backend is still the source of truth for
 * password rules; this just avoids an API round trip for an obvious typo. */
export function passwordsMatch(password: string, confirmPassword: string): boolean {
  return password.length > 0 && password === confirmPassword;
}

/** Log in and, on success, store the returned token. */
export async function submitLogin(
  email: string,
  password: string,
): Promise<AuthFlowResult> {
  try {
    const result = await login(email, password);
    setToken(result.access_token);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: messageFor(err) };
  }
}

/** Register only. Deliberately never calls `setToken()` — the backend
 * returns `UserOut` (id/email/created_at, see `RegisterResponse` in
 * lib/api.ts), not a token, so there is nothing to store here. The caller
 * sends the user to /login afterward. */
export async function submitRegister(
  email: string,
  password: string,
): Promise<AuthFlowResult> {
  try {
    await register(email, password);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: messageFor(err) };
  }
}
