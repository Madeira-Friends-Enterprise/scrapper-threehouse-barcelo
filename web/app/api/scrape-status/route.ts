import { NextResponse } from "next/server";

export const runtime = "nodejs";

const GH_API = "https://api.github.com";

export async function GET(req: Request) {
  const repo = process.env.GITHUB_REPO;
  const token = process.env.GITHUB_TOKEN;
  if (!repo || !token) {
    return NextResponse.json({ error: "Missing GitHub env vars" }, { status: 501 });
  }
  const { searchParams } = new URL(req.url);
  const runId = searchParams.get("runId");
  if (!runId) {
    return NextResponse.json({ error: "Missing runId" }, { status: 400 });
  }

  const [runRes, jobsRes] = await Promise.all([
    fetch(`${GH_API}/repos/${repo}/actions/runs/${runId}`, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
      },
      cache: "no-store",
    }),
    fetch(`${GH_API}/repos/${repo}/actions/runs/${runId}/jobs`, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
      },
      cache: "no-store",
    }),
  ]);

  if (!runRes.ok) {
    return NextResponse.json(
      { error: `GitHub API ${runRes.status}` },
      { status: 502 },
    );
  }
  const run = await runRes.json();
  const jobs = jobsRes.ok ? await jobsRes.json() : { jobs: [] };

  // Find the currently-running step label for progress text.
  const job = jobs.jobs?.[0];
  const steps = (job?.steps ?? []) as Array<{
    name: string;
    status: string;
    conclusion: string | null;
    number: number;
  }>;
  const running = steps.find((s) => s.status === "in_progress");
  const lastCompleted = [...steps]
    .reverse()
    .find((s) => s.status === "completed");
  const currentStep = running?.name ?? lastCompleted?.name ?? "Starting…";
  const completed = steps.filter((s) => s.status === "completed").length;
  const total = steps.length || 1;

  return NextResponse.json({
    status: run.status,
    conclusion: run.conclusion,
    htmlUrl: run.html_url,
    runNumber: run.run_number,
    startedAt: run.run_started_at,
    currentStep,
    progress: { completed, total },
  });
}
