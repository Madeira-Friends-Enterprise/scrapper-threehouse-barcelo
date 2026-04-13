import { NextResponse } from "next/server";

export const runtime = "nodejs";

const GH_API = "https://api.github.com";

async function gh(path: string, token: string, init?: RequestInit) {
  return fetch(`${GH_API}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
}

export async function POST() {
  const repo = process.env.GITHUB_REPO;
  const workflow = process.env.GITHUB_WORKFLOW ?? "scrape.yml";
  const token = process.env.GITHUB_TOKEN;

  if (!repo || !token) {
    return NextResponse.json(
      { error: "Missing GITHUB_REPO or GITHUB_TOKEN env vars on Vercel." },
      { status: 501 },
    );
  }

  // Remember the most recent run id BEFORE dispatch so we can detect the new one.
  const before = await gh(
    `/repos/${repo}/actions/workflows/${workflow}/runs?per_page=1`,
    token,
  );
  const beforeJson = before.ok ? await before.json() : { workflow_runs: [] };
  const previousId: number | null = beforeJson.workflow_runs?.[0]?.id ?? null;

  const dispatch = await gh(
    `/repos/${repo}/actions/workflows/${workflow}/dispatches`,
    token,
    { method: "POST", body: JSON.stringify({ ref: "main" }) },
  );
  if (!dispatch.ok) {
    const body = await dispatch.text();
    return NextResponse.json(
      { error: `GitHub dispatch failed (${dispatch.status}): ${body}` },
      { status: 502 },
    );
  }

  // Poll briefly (up to ~8s) to pick up the new run id.
  let runId: number | null = null;
  for (let i = 0; i < 8; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const after = await gh(
      `/repos/${repo}/actions/workflows/${workflow}/runs?per_page=1`,
      token,
    );
    if (after.ok) {
      const j = await after.json();
      const id = j.workflow_runs?.[0]?.id ?? null;
      if (id && id !== previousId) {
        runId = id;
        break;
      }
    }
  }

  return NextResponse.json({ ok: true, runId, workflow });
}
