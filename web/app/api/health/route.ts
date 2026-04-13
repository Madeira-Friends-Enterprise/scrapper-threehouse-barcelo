import { NextResponse } from "next/server";
import { getDataset } from "@/lib/data";

export const runtime = "nodejs";
export const revalidate = 0;

export async function GET() {
  try {
    const { meta } = await getDataset();
    return NextResponse.json({
      ok: true,
      totalRows: meta.totalRows,
      hotels: meta.hotels.length,
      lastScrapedAt: meta.lastScrapedAt,
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ ok: false, error: msg }, { status: 500 });
  }
}
