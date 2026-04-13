import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST() {
  const repo = process.env.GITHUB_REPO;        // e.g. "user/scrapper-threehouse-barcelo"
  const workflow = process.env.GITHUB_WORKFLOW ?? "scrape.yml";
  const token = process.env.GITHUB_TOKEN;

  if (!repo || !token) {
    return new NextResponse(
      "Manual refresh disabled. Set GITHUB_REPO + GITHUB_TOKEN (actions:write) env vars in Vercel.",
      { status: 501 },
    );
  }

  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });

  if (!res.ok) {
    const body = await res.text();
    return new NextResponse(`GitHub dispatch failed (${res.status}): ${body}`, { status: 502 });
  }

  return NextResponse.json({ ok: true, triggered: workflow });
}
