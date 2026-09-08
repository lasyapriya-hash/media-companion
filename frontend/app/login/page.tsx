"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { submitLogin } from "@/lib/auth-flows";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    setError(null);

    const result = await submitLogin(email.trim(), password);
    if (result.ok) {
      router.push("/");
      return; // stay disabled through the navigation, not a fresh idle state
    }
    setError(result.error);
    setLoading(false);
  }

  return (
    <main>
      <div className="page-head">
        <p className="kicker">Welcome back</p>
        <h1 className="page-title">Log In</h1>
        <p className="page-sub">
          Sign in to see your collection and get recommendations.
        </p>
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
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {error && <div className="error">{error}</div>}

        <button type="submit" disabled={loading || !email.trim() || !password}>
          {loading ? "Logging in…" : "Log In"}
        </button>
      </form>

      <p className="page-sub">
        Don&rsquo;t have an account? <Link href="/register">Register</Link>
      </p>
    </main>
  );
}
