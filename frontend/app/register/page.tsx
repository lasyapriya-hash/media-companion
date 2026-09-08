"use client";

import Link from "next/link";
import { useState } from "react";
import { passwordsMatch, submitRegister } from "@/lib/auth-flows";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    setError(null);

    if (!passwordsMatch(password, confirmPassword)) {
      setError("Passwords don't match.");
      return;
    }

    setLoading(true);
    const result = await submitRegister(email.trim(), password);
    setLoading(false);

    if (result.ok) {
      setDone(true);
    } else {
      setError(result.error);
    }
  }

  if (done) {
    return (
      <main>
        <div className="page-head">
          <p className="kicker">Almost there</p>
          <h1 className="page-title">Account Created</h1>
          <p className="page-sub">
            Your account is ready. <Link href="/login">Log in</Link> to
            continue.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main>
      <div className="page-head">
        <p className="kicker">New here</p>
        <h1 className="page-title">Register</h1>
        <p className="page-sub">Create an account to start your own collection.</p>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="email" className="field-label">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="password" className="field-label">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="confirmPassword" className="field-label">
            Confirm password
          </label>
          <input
            id="confirmPassword"
            type="password"
            autoComplete="new-password"
            required
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
        </div>

        {error && <div className="error">{error}</div>}

        <button
          type="submit"
          disabled={loading || !email.trim() || !password || !confirmPassword}
        >
          {loading ? "Creating account…" : "Register"}
        </button>
      </form>

      <p className="page-sub">
        Already have an account? <Link href="/login">Log in</Link>
      </p>
    </main>
  );
}
