import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Personal Media Companion",
  description:
    "One library for movies, series, and books, with natural-language recommendations.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="container">
          <nav className="site-nav">
            <Link href="/" className="brand">
              Media Companion
            </Link>
            <Link href="/">Library</Link>
            <Link href="/search">Search &amp; add</Link>
          </nav>
          {children}
        </div>
      </body>
    </html>
  );
}
