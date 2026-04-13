import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";
import { RefreshButton } from "@/components/RefreshButton";

export const metadata: Metadata = {
  title: "Threehouse & Barceló Prices",
  description: "Real-time nightly price scraper — live AI fetch + dashboard.",
};

const tabs = [
  { href: "/", label: "Table" },
  { href: "/heatmap", label: "Calendar" },
  { href: "/chart", label: "Monthly average" },
  { href: "/compare", label: "Compare" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-black/5 bg-white/80 backdrop-blur sticky top-0 z-10">
          <div className="mx-auto max-w-7xl px-4 h-14 flex items-center gap-4">
            <Link href="/" className="font-semibold tracking-tight text-ink">
              Threehouse & Barceló Prices
            </Link>
            <nav className="flex gap-1 ml-4">
              {tabs.map((t) => (
                <Link key={t.href} href={t.href} className="tab">
                  {t.label}
                </Link>
              ))}
            </nav>
            <div className="ml-auto">
              <RefreshButton />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
        <footer className="mx-auto max-w-7xl px-4 py-8 text-xs text-ink/50">
          Live AI scrape via OpenRouter. Cached to Google Sheets; auto-refresh every 4h.
        </footer>
      </body>
    </html>
  );
}
