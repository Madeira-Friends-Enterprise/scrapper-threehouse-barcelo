"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

export function RefreshButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [status, setStatus] = useState<string | null>(null);

  async function refresh() {
    setStatus(null);
    const res = await fetch("/api/refresh", { method: "POST" });
    if (res.ok) {
      setStatus("Scraper triggered — data available in ~2-5 min.");
      startTransition(() => router.refresh());
    } else {
      const text = await res.text();
      setStatus(`Error: ${text.slice(0, 120)}`);
    }
  }

  async function reload() {
    startTransition(() => router.refresh());
  }

  return (
    <div className="flex items-center gap-2">
      {status && <span className="text-xs text-ink/60">{status}</span>}
      <button className="btn btn-ghost" onClick={reload} disabled={pending}>
        ↻ Reload
      </button>
      <button className="btn btn-primary" onClick={refresh} disabled={pending}>
        ⚡ Scrape now
      </button>
    </div>
  );
}
