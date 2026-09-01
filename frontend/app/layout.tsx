import type { Metadata, Viewport } from "next";
import "./globals.css";
import SiteNav from "@/components/SiteNav";

export const metadata: Metadata = {
  title: "Media Companion",
  description:
    "A personal journal for the films, series, and books you watch, read, and want to — with recommendations you ask for in your own words.",
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
        <div className="wrap">
          <SiteNav />
          {children}
        </div>
      </body>
    </html>
  );
}
