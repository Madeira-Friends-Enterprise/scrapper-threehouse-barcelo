import { NextResponse } from "next/server";

export const runtime = "nodejs";

const GH_API = "https://api.github.com";

export async function POST(req: Request) {
  const repo = process.env.GITHUB_REPO;
  const token = process.env.GITHUB_TOKEN;
  if (!repo || !token) {
    return NextResponse.json(
      { error: "Missing GITHUB_REPO or GITHUB_TOKEN env vars on Vercel." },
      { status: 501 },
    );
  }
  const { searchParams } = new URL(req.url);
  const runId = searchParams.get("runId");
  if (!runId) {
    return NextResponse.json({ error: "Missing runId" }, { status: 400 });
  }

  const res = await fetch(`${GH_API}/repos/${repo}/actions/runs/${runId}/cancel`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    cache: "no-store",
  });

  if (!res.ok && res.status !== 202) {
    const body = await res.text();
    return NextResponse.json(
      { error: `GitHub cancel failed (${res.status}): ${body.slice(0, 200)}` },
      { status: 502 },
    );
  }

  return NextResponse.json({ ok: true });
}
