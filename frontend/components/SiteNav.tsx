"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Collection" },
  { href: "/search", label: "Discover" },
  { href: "/recommend", label: "Recommend" },
];

export default function SiteNav() {
  const pathname = usePathname();

  return (
    <header className="masthead">
      <Link href="/" className="masthead__brand">
        Media <span>Companion</span>
      </Link>
      <nav className="masthead__nav">
        {LINKS.map((l) => {
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
      </nav>
    </header>
  );
}
