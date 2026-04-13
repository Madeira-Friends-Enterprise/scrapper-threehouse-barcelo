"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

type Phase = "idle" | "dispatching" | "running" | "done" | "error";

type StatusResp = {
  status: string;
  conclusion: string | null;
  currentStep: string;
  progress: { completed: number; total: number };
  htmlUrl?: string;
  runNumber?: number;
};

export function RefreshButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [status, setStatus] = useState<StatusResp | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (phase !== "running") return;
    const id = setInterval(() => {
      if (startRef.current) setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    if (phase !== "running" || !runId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const res = await fetch(`/api/scrape-status?runId=${runId}`, { cache: "no-store" });
        if (!res.ok) throw new Error(`status ${res.status}`);
        const data = (await res.json()) as StatusResp;
        if (cancelled) return;
        setStatus(data);
        if (data.status === "completed") {
          if (data.conclusion === "success") {
            setPhase("done");
            startTransition(() => router.refresh());
            // Auto-dismiss after a moment.
            setTimeout(() => setPhase("idle"), 2500);
          } else {
            setPhase("error");
            setError(`Run ${data.conclusion}. See ${data.htmlUrl}`);
          }
          return;
        }
      } catch (e) {
        // swallow transient errors, keep polling
      }
      if (!cancelled) timer = setTimeout(poll, 5000);
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, runId]);

  async function start() {
    setError(null);
    setStatus(null);
    setElapsed(0);
    setPhase("dispatching");
    startRef.current = Date.now();
    try {
      const res = await fetch("/api/refresh", { method: "POST" });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setPhase("error");
        setError(json.error ?? `HTTP ${res.status}`);
        return;
      }
      if (!json.runId) {
        setPhase("error");
        setError("Could not obtain run id from GitHub.");
        return;
      }
      setRunId(json.runId);
      setPhase("running");
    } catch (e) {
      setPhase("error");
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function reload() {
    startTransition(() => router.refresh());
  }

  const active = phase === "dispatching" || phase === "running";

  return (
    <>
      <div className="flex items-center gap-2">
        <button className="btn btn-ghost" onClick={reload} disabled={pending || active}>
          ↻ Reload
        </button>
        <button className="btn btn-primary" onClick={start} disabled={active}>
          ⚡ Scrape now
        </button>
      </div>

      {(phase === "dispatching" || phase === "running" || phase === "done" || phase === "error") && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="card max-w-md w-[92%] bg-white shadow-2xl p-6 space-y-4">
            {phase === "dispatching" && (
              <>
                <div className="flex items-center gap-3">
                  <Spinner />
                  <div className="font-semibold">Triggering scraper…</div>
                </div>
                <p className="text-sm text-ink/60">
                  Dispatching GitHub Actions workflow. This usually takes a couple of seconds.
                </p>
              </>
            )}

            {phase === "running" && (
              <>
                <div className="flex items-center gap-3">
                  <Spinner />
                  <div className="font-semibold">Scraping Threehouse + Barceló…</div>
                </div>
                <div className="text-sm text-ink/70">
                  {status?.currentStep ?? "Starting…"}
                </div>
                <Progress
                  completed={status?.progress.completed ?? 0}
                  total={status?.progress.total ?? 1}
                />
                <div className="flex justify-between text-xs text-ink/50">
                  <span>
                    Elapsed: {fmtDuration(elapsed)}
                    {status?.runNumber ? ` · run #${status.runNumber}` : ""}
                  </span>
                  <span>Typical: 2–4 min</span>
                </div>
                <p className="text-xs text-ink/50">
                  The overlay closes automatically when new prices are saved to Google Sheets.
                </p>
              </>
            )}

            {phase === "done" && (
              <>
                <div className="flex items-center gap-3">
                  <div className="w-6 h-6 rounded-full bg-emerald-500 text-white flex items-center justify-center text-sm">✓</div>
                  <div className="font-semibold">Scrape complete</div>
                </div>
                <p className="text-sm text-ink/60">Refreshing data…</p>
              </>
            )}

            {phase === "error" && (
              <>
                <div className="flex items-center gap-3">
                  <div className="w-6 h-6 rounded-full bg-rose-500 text-white flex items-center justify-center text-sm">!</div>
                  <div className="font-semibold">Scrape failed</div>
                </div>
                <p className="text-sm text-rose-700 break-words">{error}</p>
                <div className="flex gap-2 justify-end">
                  <button className="btn btn-ghost" onClick={() => setPhase("idle")}>
                    Close
                  </button>
                  <button className="btn btn-primary" onClick={start}>
                    Retry
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function Spinner() {
  return (
    <span
      className="inline-block w-5 h-5 rounded-full border-2 border-black/10 border-t-accent animate-spin"
      aria-hidden
    />
  );
}

function Progress({ completed, total }: { completed: number; total: number }) {
  const pct = Math.min(100, Math.round((completed / Math.max(total, 1)) * 100));
  return (
    <div className="w-full h-2 bg-black/5 rounded-full overflow-hidden">
      <div
        className="h-full bg-accent transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function fmtDuration(s: number) {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}
