"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { deriveAuthState } from "@/lib/auth-guard";

const LINKS = [
  { href: "/", label: "Collection" },
  { href: "/search", label: "Discover" },
  { href: "/recommend", label: "Recommend" },
];

export default function SiteNav() {
  const pathname = usePathname();
  const { isAuthenticated, checked, logout } = useAuth();
  const authState = deriveAuthState(checked, isAuthenticated);

  return (
    <header className="masthead">
      <Link href="/" className="masthead__brand">
        Media <span>Companion</span>
      </Link>
      <nav className="masthead__nav">
        {authState === "authenticated" &&
          LINKS.map((l) => {
            const active =
              l.href === "/"
                ? pathname === "/" || pathname.startsWith("/item")
                : pathname.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={active ? "is-active" : undefined}
              >
                {l.label}
              </Link>
            );
          })}

        {authState === "authenticated" && (
          <button type="button" onClick={logout}>
            Log Out
          </button>
        )}

        {authState === "unauthenticated" && (
          <>
            <Link
              href="/login"
              className={pathname === "/login" ? "is-active" : undefined}
            >
              Log In
            </Link>
            <Link
              href="/register"
              className={pathname === "/register" ? "is-active" : undefined}
            >
              Register
            </Link>
          </>
        )}
      </nav>
    </header>
  );
}
