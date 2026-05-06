import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";
import { RefreshButton } from "@/components/RefreshButton";

export const metadata: Metadata = {
  title: "Savoy Booking Prices",
  description: "Per-day Booking.com prices for Savoy Insular V and Savoy Monumentalis VII.",
};

const tabs = [
  { href: "/", label: "Table" },
  { href: "/heatmap", label: "Calendar" },
  { href: "/chart", label: "Monthly average" },
  { href: "/compare", label: "Compare" },
  { href: "/history", label: "History" },
  { href: "/pricing", label: "Pricing rules" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-black/5 bg-white/80 backdrop-blur sticky top-0 z-10">
          <div className="mx-auto max-w-7xl px-4 h-14 flex items-center gap-4">
            <Link href="/" className="font-semibold tracking-tight text-ink">
              Savoy Booking Prices
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
      </body>
    </html>
  );
}
